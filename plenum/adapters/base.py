from __future__ import annotations
import logging
from typing import Iterable

from ..models import Kalla, Observation
from ..normalize import berika

log = logging.getLogger("plenum.adapter")


class Adapter:
    """Basklass. Underklasser implementerar `samla()` och yieldar Observation.

    Kontrakt: adaptern får bara returnera det som faktiskt står på sidan.
    Tomt fält betyder "saknas i källan". Varje observation ska ha kalla_url
    så att raden går att verifiera manuellt.
    """
    namn = "base"

    def __init__(self, kalla: Kalla, hamtare):
        self.kalla = kalla
        self.h = hamtare

    def samla(self) -> Iterable[Observation]:
        raise NotImplementedError

    def kor(self) -> list[Observation]:
        ut: list[Observation] = []
        for obs in self.samla():
            if not obs.namn_raw.strip():
                continue
            berika(obs)
            hint = getattr(obs, "organ_kategori_hint", "")
            if hint and obs.organ_typ == "ovrigt":
                obs.organ_typ = hint
            if not obs.efternamn:
                continue
            ut.append(obs)
        # dedupe på naturlig nyckel (samma person+roll+organ kan stå på flera sidor)
        seen = {}
        for o in ut:
            k = o.nyckel()
            if k not in seen or (not seen[k].epost and o.epost):
                seen[k] = o
        return list(seen.values())
