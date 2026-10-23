"""Adapter för hemmasnickrade kommunsajter med tabeller/listor.

Konfigureras per kommun i config/kallor.csv:
  base_url  = startsida med länkar till organ, ELLER en enda sida med allt
  extra     = JSON, t.ex. {"organ_lankar": "a[href*='namnd']", "organ_rubrik": "h1"}
Om organ_lankar saknas tolkas bara base_url. Rubriken på sidan (h1) blir
organnamn om inte tabellen själv har en organ-kolumn.
"""
from __future__ import annotations
from urllib.parse import urljoin, urlparse

from .base import Adapter
from .tabell import tolka_tabeller, tolka_listor, _text


class GenericTableAdapter(Adapter):
    namn = "generic_table"

    def _organ_namn(self, page, fallback: str) -> str:
        sel = self.kalla.extra.get("organ_rubrik", "h1")
        el = page.css(sel)
        return _text(el[0]) if el else fallback

    def _organ_sidor(self, start) -> list[tuple[str, str]]:
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

    def samla(self):
        start = self.h.get(self.kalla.base_url)
        for url, lanktext in self._organ_sidor(start):
            page = start if url == start.url else self.h.get(url)
            organ = self._organ_namn(page, lanktext or self.kalla.organisation)
            n = 0
            for obs in tolka_tabeller(page, self.kalla.org_slug, organ, url):
                n += 1
                yield obs
            if n == 0:
                for obs in tolka_listor(page, self.kalla.org_slug, organ, url):
                    yield obs
