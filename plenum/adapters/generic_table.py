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
SKRAP_RUBRIK = re.compile(r"kakor|cookie|skriv ut|kontakt|sök |^sök$|startsida|underhåll|hitta din|"
                          r"meny|navigering|genvägar|lyssna|translate|^kommun och politik$|"
                          r"^politik och demokrati$|^politisk organisation$|^nämnder$|^utskott$|^förtroendevalda$|"
                          r"^om \S+\.se$|lista med|dela sidan|mer om oss|other languages|engagera dig|"
                          r"mandatfördelning|delegationsordning|arvodesreglemente|^ledamöter$|^ersättare$|"
                          r"synpunkter|sociala medier|mejl till|hitta snabbt|nämndernas funktion|motioner", re.I)
_SVANS = re.compile(r"(s)?\s+(ledamöter och ersättare|ledamöter|ersättare|förtroendevalda|"
                    r"politiker|sammansättning|ledamot)$", re.I)


_PREFIX = re.compile(r"^(ledamöter och ersättare i|ledamöter i|ersättare i|politiker i|förtroendevalda i|"
                     r"sammansättning i)\s+", re.I)
_PERIOD = re.compile(r"\b(20\d\d)\s*(?:\([a-zåäö]+\))?\s*[-–]\s*(20\d\d)\b")


def rensa_organnamn(n: str) -> str:
    n = re.sub(r"\s+", " ", n or "").strip()
    n = _PREFIX.sub("", n)
    n = _PERIOD.sub("", n).replace("()", "").strip(" ,-–")
    m = _SVANS.search(n)
    if m and len(n[: m.start()]) > 3:
        n = n[: m.start()]
    return n[:1].upper() + n[1:]


def period_ur(n: str) -> str:
    m = _PERIOD.search(n or "")
    return f"{m.group(1)}-{m.group(2)}" if m else ""


class GenericTableAdapter(Adapter):
    namn = "generic_table"

    def _organ_namn(self, page, fallback: str) -> str:
        """Sidans rubrik i huvudinnehållet. Rubriker från kakbanners, utskriftsknappar,
        sidhuvud m.m. hoppas över (provkörningen 2026-10-25 gav t.ex. 'Skriv ut',
        'Vi använder kakor' och kommunens namn som organnamn)."""
        sel = self.kalla.extra.get("organ_rubrik")
        kandidater = [_text(e) for e in page.css(sel)] if sel else []
        if not kandidater:
            for s in ("main h1", "article h1", "#content h1", "[role=main] h1", ".sv-text-portlet h1", "h1", "h2"):
                kandidater += [_text(e) for e in page.css(s)]
        kommun = self.kalla.organisation.lower()
        for k in kandidater:
            if k and not SKRAP_RUBRIK.search(k) and k.lower().strip() not in (kommun, f"{kommun} kommun", f"{kommun}s kommun"):
                return rensa_organnamn(k)
        titel = (page.css("title::text").get() or "").split(" - ")[0].split(" | ")[0].strip()
        for k in (fallback, titel):
            if k and not SKRAP_RUBRIK.search(k):
                return rensa_organnamn(k)
        return ""

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
            organ = self._organ_namn(page, lanktext)
            if not organ:
                continue
            rubriker = " ".join(_text(e) for e in page.css("h1"))
            period = period_ur(rubriker) or period_ur(lanktext)
            n = 0
            for obs in tolka_tabeller(page, self.kalla.org_slug, organ, url):
                n += 1
                obs.mandatperiod = period
                yield obs
            if n == 0:
                for obs in tolka_listor(page, self.kalla.org_slug, organ, url):
                    obs.mandatperiod = period
                    yield obs
