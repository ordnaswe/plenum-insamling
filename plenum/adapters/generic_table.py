"""Adapter för kommuner med egen webbplats (oftast SiteVision eller Episerver).

Två lägen, styrs av kolumnen extra (JSON) i config/kallor.csv:
  {"organ_lankar": "<css>"}   handkonfigurerat: följ länkarna som matchar selektorn
  {"auto": true}              automatiskt: base_url är kartläggningens bästa sida; adaptern
                              besöker den och dess överordnade sida, och följer länkar som ser
                              ut att leda till organ (nämnd, styrelse, fullmäktige, bolag, AB ...)
Varje sida tolkas med den gemensamma tabell-/listtolkaren. Organnamn = sidans h1, rensat
från tillägg som "s ledamöter". Max antal sidor: extra.max_sidor (standard 40).
"""
from __future__ import annotations
import re
from urllib.parse import urljoin, urlparse

from .base import Adapter
from .tabell import tolka_tabeller, tolka_listor, _text

ORGAN_ORD = re.compile(r"nämnd|namnd|styrelse|fullmäktige|fullmaktige|utskott|bolag|\bab\b|"
                       r"\bråd\b|rådet|-rad\b|revision|beredning|förbund|forbund|ledamöter|ledamoter|"
                       r"förtroendevald|fortroendevald|presidi", re.I)
NEJ = re.compile(r"protokoll|kallelse|sammanträde|sammantrade|handling|arkiv|valet|webb-?tv|"
                 r"lediga|kontakt|felanmäl|e-tjänst|cookie|tillgänglighet|\.pdf$|mailto:", re.I)
_SVANS = re.compile(r"(s)?\s+(ledamöter och ersättare|ledamöter|ersättare|förtroendevalda|"
                    r"politiker|sammansättning|ledamot)$", re.I)


def rensa_organnamn(n: str) -> str:
    n = re.sub(r"\s+", " ", n or "").strip()
    m = _SVANS.search(n)
    if m and len(n[: m.start()]) > 3:
        n = n[: m.start()]
    return n


class GenericTableAdapter(Adapter):
    namn = "generic_table"

    def _organ_namn(self, page, fallback: str) -> str:
        sel = self.kalla.extra.get("organ_rubrik", "h1")
        el = page.css(sel)
        return rensa_organnamn(_text(el[0]) if el else fallback)

    def _manuella_sidor(self, start) -> list[tuple[str, str]]:
        sel = self.kalla.extra.get("organ_lankar")
        if not sel:
            return [(start.url, "")]
        ut, sedda = [], set()
        bas_host = urlparse(start.url).netloc
        for a in start.css(sel):
            href = a.attrib.get("href") if hasattr(a, "attrib") else None
            if not href:
                continue
            url = urljoin(start.url, href)
            if urlparse(url).netloc != bas_host or url in sedda or "#" in url:
                continue
            sedda.add(url)
            ut.append((url, _text(a)))
        return ut[: int(self.kalla.extra.get("max_sidor", 300))]

    def _auto(self, start):
        """Bredden först från startsidan och dess överordnade sida."""
        host = urlparse(start.url).netloc
        max_sidor = int(self.kalla.extra.get("max_sidor", 40))
        ko = [(start.url, start, "")]
        p = urlparse(start.url)
        delar = [d for d in p.path.split("/") if d]
        # överordnade sidor (en och två nivåer upp) brukar lista nämnder, styrelser och bolag
        for n in (1, 2):
            if len(delar) > n:
                ko.append((f"{p.scheme}://{p.netloc}/" + "/".join(delar[:-n]), None, ""))
        sedda = {u for u, _, _ in ko}
        besokta = 0
        while ko and besokta < max_sidor:
            url, page, lanktext = ko.pop(0)
            if page is None:
                try:
                    page = self.h.get(url)
                except Exception:
                    continue
                if page.status != 200:
                    continue
            besokta += 1
            yield url, page, lanktext
            for a in page.css("a"):
                href = a.attrib.get("href") or ""
                if not href or href.startswith(("#", "javascript:", "mailto:", "tel:")):
                    continue
                u = urljoin(url, href).split("#")[0].split("?")[0]
                t = _text(a)
                if urlparse(u).netloc != host or u in sedda:
                    continue
                if NEJ.search(u) or NEJ.search(t) or not (ORGAN_ORD.search(t) or ORGAN_ORD.search(u)):
                    continue
                sedda.add(u)
                ko.append((u, None, t))

    def samla(self):
        start = self.h.get(self.kalla.base_url)
        if self.kalla.extra.get("auto"):
            sidor = self._auto(start)
        else:
            sidor = ((u, start if u == start.url else self.h.get(u), t) for u, t in self._manuella_sidor(start))
        for url, page, lanktext in sidor:
            organ = self._organ_namn(page, lanktext or self.kalla.organisation)
            n = 0
            for obs in tolka_tabeller(page, self.kalla.org_slug, organ, url):
                n += 1
                yield obs
            if n == 0:
                for obs in tolka_listor(page, self.kalla.org_slug, organ, url):
                    yield obs
