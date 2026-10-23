"""Läser config/kallor.csv till Kalla-objekt."""
from __future__ import annotations
import csv
import json
import re
import unicodedata

from .models import Kalla


def slugga(namn: str) -> str:
    s = unicodedata.normalize("NFKD", namn).encode("ascii", "ignore").decode().lower()
    s = re.sub(r"[^a-z0-9]+", "-", s).strip("-")
    return s


def las_kallor(path: str = "config/kallor.csv", bara_aktiva: bool = True) -> list[Kalla]:
    ut = []
    with open(path, encoding="utf-8") as f:
        for r in csv.DictReader(f):
            if not r.get("organisation"):
                continue
            extra = json.loads(r.get("extra") or "{}")
            k = Kalla(
                org_slug=r.get("org_slug") or slugga(r["organisation"]),
                organisation=r["organisation"].strip(),
                kommunkod=(r.get("kommunkod") or "").strip(),
                typ=(r.get("typ") or "kommun").strip(),
                system=(r.get("system") or "").strip(),
                adapter=(r.get("adapter") or "manual").strip(),
                base_url=(r.get("base_url") or "").strip(),
                aktiv=(r.get("aktiv") or "1").strip() in {"1", "true", "ja", "x"},
                kommentar=(r.get("kommentar") or "").strip(),
                extra=extra,
            )
            if bara_aktiva and not k.aktiv:
                continue
            ut.append(k)
    return ut
