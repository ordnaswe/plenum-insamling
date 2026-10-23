"""Adapter för Troman Publik ([kund].tromanpublik.se).

Struktur, verifierad mot haninge.tromanpublik.se 2026-10-23:
  /                          startsida, länkar till /organisationstyp/<id> och /organisation/<id>
  /organisationstyp/<id>     kategori (Nämnder, Bolag ...), länkar till /organisation/<id>
  /organisation/<id>         h1 = organnamn, "Mandatperiod: ÅÅÅÅ-MM-DD - ÅÅÅÅ-MM-DD",
                             table#engagementTable med kolumner Efternamn | Förnamn | Parti | Uppdrag | Ordningsnummer,
                             person länkad som /person/<id>, breadcrumb visar kategorin
  /person/<id>               personsida (e-post hämtas härifrån när PLENUM_PERSONSIDOR=1)
  /sok?allpersons=true       lista över alla personer

Vi hämtar bara det som behövs: startsidan, kategorisidorna och varje organsida.
Personsidorna (en per person) hämtas bara när PLENUM_PERSONSIDOR=1, t.ex. veckovis.
"""
from __future__ import annotations
import os
import re
from urllib.parse import urljoin, urlparse

from .base import Adapter
from .tabell import tolka_tabeller, _text, _epost_i
from ..models import Observation

_ORG = re.compile(r"/organisation/([0-9a-f-]{20,})", re.I)
_TYP = re.compile(r"/organisationstyp/([0-9a-f-]{20,})", re.I)
_PERSON = re.compile(r"/person/([0-9a-f-]{20,})", re.I)
_MANDAT = re.compile(r"Mandatperiod:?\s*(\d{4})-\d{2}-\d{2}\s*-\s*(\d{4})-\d{2}-\d{2}")

# Tromans kategorinamn -> vår organtyp, används bara om namnheuristiken ger 'ovrigt'
KATEGORI = {"bolag": "bolag", "nämnder": "namnd", "namnder": "namnd", "stiftelser": "stiftelse",
            "förbund": "forbund", "forbund": "forbund", "råd": "rad", "rad": "rad", "revision": "revision"}


class TromanAdapter(Adapter):
    namn = "troman"

    def __init__(self, kalla, hamtare):
        super().__init__(kalla, hamtare)
        self.max_sidor = int((kalla.extra or {}).get("max_sidor", 400))
        self.personsidor = os.getenv("PLENUM_PERSONSIDOR", "0") == "1"

    def _lankar(self, page, rx) -> dict[str, str]:
        host = urlparse(page.url).netloc
        ut = {}
        for a in page.css("a"):
            href = a.attrib.get("href") or ""
            m = rx.search(href)
            if not m:
                continue
            url = urljoin(page.url, href)
            if urlparse(url).netloc == host:
                ut.setdefault(url, _text(a))
        return ut

    def samla(self):
        start = self.h.get(self.kalla.base_url)
        organ_urls = self._lankar(start, _ORG)
        for typ_url in list(self._lankar(start, _TYP)):
            sida = self.h.get(typ_url)
            for u, t in self._lankar(sida, _ORG).items():
                organ_urls.setdefault(u, t)

        person_urls: dict[str, str] = {}
        ko, besokta = list(organ_urls), set()
        while ko and len(besokta) < self.max_sidor:
            url = ko.pop(0)
            if url in besokta:
                continue
            besokta.add(url)
            page = self.h.get(url)
            # organ som bara länkas från andra organsidor (t.ex. utskott under en nämnd)
            for u, t in self._lankar(page, _ORG).items():
                if u not in besokta and u not in organ_urls:
                    organ_urls[u] = t
                    ko.append(u)
            h1 = page.css("h1")
            organ = _text(h1[0]) if h1 else organ_urls[url]
            if not organ:
                continue
            kategori = ""
            bc = page.css(".breadcrumb a")
            if bc:
                kategori = _text(bc[-1]).strip().lower()
            m = _MANDAT.search(page.get_all_text(separator=" "))
            mandat = f"{m.group(1)}-{m.group(2)}" if m else ""
            extern_organ_id = (_ORG.search(url) or [None, ""])[1] if _ORG.search(url) else ""
            for obs in tolka_tabeller(page, self.kalla.org_slug, organ, url):
                obs.mandatperiod = mandat
                obs.extern_organ_id = extern_organ_id
                obs.organ_kategori_hint = KATEGORI.get(kategori, "")
                if obs.extern_person_id:
                    person_urls.setdefault(urljoin(url, f"/person/{obs.extern_person_id}"), obs.namn_raw)
                yield obs

        if self.personsidor:
            for url, namn in list(person_urls.items())[: self.max_sidor * 5]:
                yield from self._personsida(url, namn)

    # Personsida, verifierad 2026-10-23: h1 "Förnamn Efternamn (P)", "E-post:" med mailto-länk,
    # tabell Organisation | Uppdrag | Start | Slut med organ länkat som /organisation/<id>.
    def _personsida(self, url: str, namn_fallback: str):
        page = self.h.get(url)
        h1 = page.css("h1")
        h1txt = _text(h1[0]) if h1 else ""
        m = re.match(r"^(.*?)\s*\(\s*([^()]*?)\s*\)\s*$", h1txt)
        namn, parti = (m.group(1).strip(), m.group(2).strip()) if m else (h1txt or namn_fallback, "")
        pid = _PERSON.search(url).group(1)
        epost = _epost_i(page)
        idag = __import__("datetime").date.today().isoformat()
        n = 0
        for tabell in page.css("table"):
            rader = tabell.css("tr")
            rub = [_text(c) for c in rader[0].css("th,td")] if rader else []
            if not rub or not rub[0].lower().startswith("organisation"):
                continue
            for tr in rader[1:]:
                c = [_text(x) for x in tr.css("td")]
                if len(c) < 2 or not c[0]:
                    continue
                start = c[2] if len(c) > 2 and re.match(r"\d{4}-\d{2}-\d{2}", c[2]) else ""
                slut = c[3] if len(c) > 3 and re.match(r"\d{4}-\d{2}-\d{2}", c[3]) else ""
                if slut and slut < idag:
                    continue  # avslutat uppdrag: visas inte som aktivt
                href = tr.css("a::attr(href)").get() or ""
                oid = _ORG.search(href).group(1) if _ORG.search(href) else ""
                n += 1
                yield Observation(org_slug=self.kalla.org_slug, organ_namn=c[0], namn_raw=namn,
                                  roll_raw=c[1], parti_raw=parti, epost=epost, kalla_url=url,
                                  extern_person_id=pid, extern_organ_id=oid,
                                  start_datum=start, slut_datum=slut)
        if n == 0 and epost:
            yield Observation(org_slug=self.kalla.org_slug, organ_namn="", namn_raw=namn, roll_raw="",
                              parti_raw=parti, epost=epost, kalla_url=url, extern_person_id=pid)
