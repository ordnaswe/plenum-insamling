"""Hämtning med Scrapling.

Strategi mot blockering (i den ordningen):
1. FetcherSession med Chrome-TLS-fingerprint och "stealthy headers". Det
   räcker för de flesta kommunsajter och Troman Publik, som inte har
   aggressivt botskydd. Vi uppträder som en vanlig webbläsare.
2. Per-domän-paus med slump (standard 1,5-3,5 s). Kommunerna är små
   servrar; vi vill aldrig vara den som sänker dem. Totalt är det några
   tusen sidor per dygn, utspritt över GitHub Actions-matrisen.
3. Vid 403/429/503, Cloudflare-interstitial eller misstänkt tom sida:
   backoff och nytt försök, därefter fallback till StealthyFetcher
   (riktig headless Chromium med fingerprint-spoofing) om PLENUM_BROWSER=1.
4. Om även det blockeras: markera körningen "blockerad" i Supabase och gå
   vidare. Nästa dag försöker vi igen. En proxyrotator kan kopplas in via
   PLENUM_PROXY (http://user:pass@host:port) om en viss sajt visar sig
   blocka GitHubs IP-intervall.

Vi läser robots.txt och respekterar Disallow för de sökvägar vi hämtar.
Offentliga uppgifter om förtroendevalda är öppna data i praktiken, men
det är ändå rimligt att följa sajtens egna regler.
"""
from __future__ import annotations
import logging
import os
import random
import time
import urllib.robotparser
from urllib.parse import urlparse

from scrapling.fetchers import FetcherSession

log = logging.getLogger("plenum.fetch")

UA_HINT = "PlenumBot/0.1 (+https://plenum.se/om-insamling; kontakt@plenum.se)"
MIN_PAUS = float(os.getenv("PLENUM_MIN_PAUS", "1.5"))
MAX_PAUS = float(os.getenv("PLENUM_MAX_PAUS", "3.5"))
BLOCK_STATUS = {403, 429, 503, 502, 520, 521, 522}


class Blockerad(Exception):
    pass


class Hamtare:
    def __init__(self, browser_fallback: bool | None = None, proxy: str | None = None):
        self.browser_fallback = (
            browser_fallback if browser_fallback is not None
            else os.getenv("PLENUM_BROWSER", "0") == "1"
        )
        self.proxy = proxy or os.getenv("PLENUM_PROXY") or None
        self._senast: dict[str, float] = {}
        self._robots: dict[str, urllib.robotparser.RobotFileParser | None] = {}
        self._session = None
        self.antal_hamtningar = 0

    # -- livscykel --
    def __enter__(self):
        self._session = FetcherSession(
            impersonate="chrome", stealthy_headers=True, timeout=40,
            retries=2, retry_delay=2, proxy=self.proxy,
            headers={"Accept-Language": "sv-SE,sv;q=0.9,en;q=0.5"},
        ).__enter__()
        return self

    def __exit__(self, *exc):
        if self._session is not None:
            try:
                self._session.__exit__(*exc)
            except Exception:
                pass

    # -- artighet --
    def _paus(self, host: str):
        nu = time.monotonic()
        senast = self._senast.get(host, 0.0)
        vanta = random.uniform(MIN_PAUS, MAX_PAUS) - (nu - senast)
        if vanta > 0:
            time.sleep(vanta)
        self._senast[host] = time.monotonic()

    def _tillaten(self, url: str) -> bool:
        p = urlparse(url)
        root = f"{p.scheme}://{p.netloc}"
        if root not in self._robots:
            rp = urllib.robotparser.RobotFileParser()
            try:
                r = self._session.get(f"{root}/robots.txt")
                if r.status == 200 and r.body:
                    rp.parse(r.body.decode(r.encoding or "utf-8", "ignore").splitlines())
                    self._robots[root] = rp
                else:
                    self._robots[root] = None
            except Exception:
                self._robots[root] = None
        rp = self._robots[root]
        return True if rp is None else rp.can_fetch("*", url)

    # -- hämtning --
    def get(self, url: str, *, wait_selector: str | None = None):
        """Returnerar ett Scrapling Response (css/xpath/urljoin finns på objektet)."""
        if not self._tillaten(url):
            log.warning("robots.txt förbjuder %s", url)
            raise Blockerad(f"robots.txt: {url}")
        host = urlparse(url).netloc
        self._paus(host)
        self.antal_hamtningar += 1
        r = self._session.get(url)
        if r.status in BLOCK_STATUS or self._ser_blockerad_ut(r):
            log.warning("Troligen blockerad (%s) %s", r.status, url)
            time.sleep(random.uniform(8, 15))
            r = self._session.get(url)
            if r.status in BLOCK_STATUS or self._ser_blockerad_ut(r):
                if self.browser_fallback:
                    return self._browser_get(url, wait_selector)
                raise Blockerad(f"{r.status} {url}")
        return r

    @staticmethod
    def _ser_blockerad_ut(r) -> bool:
        if r.status != 200:
            return False
        kropp = (r.body or b"")[:4000].lower()
        return (b"cf-chl" in kropp or b"just a moment" in kropp
                or b"access denied" in kropp or b"captcha" in kropp)

    def _browser_get(self, url: str, wait_selector: str | None):
        from scrapling.fetchers import StealthyFetcher
        log.info("Fallback till headless-webbläsare: %s", url)
        kw = dict(headless=True, solve_cloudflare=True, network_idle=True)
        if wait_selector:
            kw["wait_selector"] = wait_selector
        if self.proxy:
            kw["proxy"] = self.proxy
        r = StealthyFetcher.fetch(url, **kw)
        if r.status in BLOCK_STATUS:
            raise Blockerad(f"browser {r.status} {url}")
        return r
