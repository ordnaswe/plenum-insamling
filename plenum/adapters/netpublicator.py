"""Adapter för Netpublicators förtroendevaldaregister.

Struktur, verifierad mot Älmhults register 2026-10-24
(https://www.netpublicator.com/elected/registry/0cc29b7c2c784c8c8790ae6838bd0078/):
  /politicians                 alla personer: Förnamn | Efternamn | Parti (logotyp med alt-text),
                               plus <select id="board"> med alla instanser (id + namn)
  /board/<id>                  h1 = instansens namn, tabell: Förnamn | Efternamn | Uppdrag | Parti
  /politician/<id>             h1 = namn, "Parti:", "Epost organisation:" (mailto),
                               tabell Instans | Uppdrag
Används även inbäddat av kommuner (t.ex. Lund), men vi hämtar alltid direkt från netpublicator.com.

base_url i kallor.csv: https://www.netpublicator.com/elected/registry/<registry-id>/
Personsidor (e-post) hämtas bara när PLENUM_PERSONSIDOR=1, som för Troman.
"""
from __future__ import annotations
import os
import re
from urllib.parse import urljoin

from .base import Adapter
from .tabell import tolka_tabeller, _text, _epost_i
from ..models import Observation

_REG = re.compile(r"/elected/registry/([0-9a-f]{32})", re.I)
_POL = re.compile(r"/politician/([0-9a-f-]{20,})", re.I)


def registry_rot(url: str) -> str:
    from urllib.parse import urlparse
    m = _REG.search(url or "")
    if not m:
        raise ValueError(f"Ingen Netpublicator-registeradress: {url}")
    u = urlparse(url)
    return f"{u.scheme}://{u.netloc}/elected/registry/{m.group(1)}/"


class NetpublicatorAdapter(Adapter):
    namn = "netpublicator"

    def __init__(self, kalla, hamtare):
        super().__init__(kalla, hamtare)
        self.rot = registry_rot(kalla.base_url)
        self.personsidor = os.getenv("PLENUM_PERSONSIDOR", "0") == "1"

    def samla(self):
        lista = self.h.get(urljoin(self.rot, "politicians"))
        instanser = [(o.attrib.get("value"), _text(o)) for o in lista.css("select#board option")
                     if o.attrib.get("value")]
        if not instanser:
            raise ValueError("Hittade inga instanser i registret (strukturen kan ha ändrats)")
        for bid, namn in instanser:
            url = urljoin(self.rot, f"board/{bid}")
            page = self.h.get(url)
            h1 = page.css("h1")
            organ = _text(h1[0]) if h1 else namn
            for obs in tolka_tabeller(page, self.kalla.org_slug, organ or namn, url):
                obs.extern_organ_id = bid
                yield obs
        if self.personsidor:
            pids = []
            for href in lista.css("a::attr(href)").getall():
                m = _POL.search(href or "")
                if m and m.group(1) not in pids:
                    pids.append(m.group(1))
            for pid in pids:
                yield from self._personsida(urljoin(self.rot, f"politician/{pid}"), pid)

    def _personsida(self, url: str, pid: str):
        page = self.h.get(url)
        h1 = page.css("h1")
        namn = _text(h1[0]) if h1 else ""
        if not namn:
            return
        parti = ""
        for li in page.css("li.list-group-item"):
            t = _text(li)
            if t.lower().endswith("parti:") or t.lower().startswith("parti:"):
                parti = re.sub(r"\s*Parti:\s*", " ", t, flags=re.I).strip()
        epost = _epost_i(page)
        n = 0
        for tabell in page.css("table"):
            rader = tabell.css("tr")
            rub = [_text(c).lower() for c in rader[0].css("th,td")] if rader else []
            if "instans" not in rub:
                continue
            i_org, i_roll = rub.index("instans"), rub.index("uppdrag") if "uppdrag" in rub else -1
            for tr in rader[1:]:
                c = tr.css("td")
                if len(c) <= max(i_org, i_roll):
                    continue
                organ = _text(c[i_org])
                if not organ:
                    continue
                href = c[i_org].css("a::attr(href)").get() or ""
                bid = href.rstrip("/").split("/")[-1] if "/board/" in href else ""
                n += 1
                yield Observation(org_slug=self.kalla.org_slug, organ_namn=organ, namn_raw=namn,
                                  roll_raw=_text(c[i_roll]) if i_roll >= 0 else "", parti_raw=parti,
                                  epost=epost, kalla_url=url, extern_person_id=pid, extern_organ_id=bid)
        if n == 0 and epost:
            yield Observation(org_slug=self.kalla.org_slug, organ_namn="", namn_raw=namn, roll_raw="",
                              parti_raw=parti, epost=epost, kalla_url=url, extern_person_id=pid)
