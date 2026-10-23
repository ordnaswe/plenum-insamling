from __future__ import annotations
import hashlib
from dataclasses import dataclass, asdict, field


@dataclass
class Observation:
    """En observerad rad: en person med en roll i ett organ hos en organisation.

    Allt som kommer från källan sparas som *_raw. Normaliserade fält fylls av
    normalize.py. Inget gissas: tomt fält = okänt.
    """
    org_slug: str                 # t.ex. "haninge", "region-skane"
    organ_namn: str               # som källan skriver det
    namn_raw: str
    roll_raw: str
    parti_raw: str = ""
    epost: str = ""
    kalla_url: str = ""
    extern_person_id: str = ""    # källans eget id om det finns
    extern_organ_id: str = ""
    mandatperiod: str = ""        # t.ex. "2026-2030" om källan anger det
    start_datum: str = ""         # ISO-datum om källan anger det (Troman personsida)
    slut_datum: str = ""
    # normaliserat
    fornamn: str = ""
    efternamn: str = ""
    namn_osakert: bool = False
    parti: str = ""               # S, M, SD, C, V, KD, L, MP eller lokalt partinamn
    roll: str = "ovrigt"
    organ_typ: str = "ovrigt"
    organ_norm: str = ""

    def nyckel(self) -> str:
        """Naturlig nyckel för uppdraget (stabil mellan körningar)."""
        base = "|".join([self.org_slug, self.organ_norm, self.fornamn.lower(),
                         self.efternamn.lower(), self.roll])
        return hashlib.sha1(base.encode("utf-8")).hexdigest()[:20]

    def person_nyckel(self) -> str:
        base = "|".join([self.org_slug, self.fornamn.lower(), self.efternamn.lower()])
        return hashlib.sha1(base.encode("utf-8")).hexdigest()[:20]

    def to_dict(self) -> dict:
        d = asdict(self)
        d["uppdrag_nyckel"] = self.nyckel()
        d["person_nyckel"] = self.person_nyckel()
        return d


@dataclass
class Kalla:
    """En rad i config/kallor.csv."""
    org_slug: str
    organisation: str
    kommunkod: str
    typ: str            # kommun | region
    system: str         # troman | egen | ingen | (namn på system 2 när vi vet det)
    adapter: str        # troman | generic_table | manual
    base_url: str
    aktiv: bool = True
    kommentar: str = ""
    extra: dict = field(default_factory=dict)
