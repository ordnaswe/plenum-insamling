"""Importerar Plenums rådata 2022-2026 (CSV: full_name, kom_name, parti_name,
namnder_med_roller) till samma Observation-format, med mandatperiod '2022-2026'.

  python -m plenum.import_legacy data/raw/politiker_*.csv --out data/legacy.jsonl
  python -m plenum.import_legacy data/raw/politiker_*.csv --supabase   # skriver till Supabase

Format på namnder_med_roller: "Organ A (Roll), Organ B (Roll), ...". Organ kan
innehålla kommatecken ("Barn-, utbildnings- och kulturnämnden (Ledamot)") så vi
splittar på ")," och inte på ",".
"""
from __future__ import annotations
import argparse
import csv
import re

from .kallor import slugga
from .models import Observation, Kalla
from .normalize import berika
from .store import skriv_jsonl

_DEL = re.compile(r"\)\s*,\s*")
_ORGAN_ROLL = re.compile(r"^(?P<organ>.+?)\s*\((?P<roll>[^()]*)\)\s*$")


NAMN2SLUG: dict[str, str] = {}   # fylls från kallor.csv i main(); annars slugga()


def org_slug_for(kom_name: str) -> str:
    return NAMN2SLUG.get(kom_name.strip(), slugga(kom_name))


def tolka_rad(r: dict) -> list[Observation]:
    namn = (r.get("full_name") or "").strip()
    org = (r.get("kom_name") or "").strip()
    parti = (r.get("parti_name") or "").strip()
    if not namn or namn == "-" or not org:
        return []
    ut = []
    for bit in _DEL.split((r.get("namnder_med_roller") or "").strip()):
        bit = bit.strip()
        if not bit:
            continue
        if not bit.endswith(")"):
            bit += ")"
        m = _ORGAN_ROLL.match(bit)
        if not m:
            continue
        ut.append(Observation(org_slug=org_slug_for(org), organ_namn=m.group("organ").strip(),
                              namn_raw=namn, roll_raw=m.group("roll").strip(), parti_raw=parti,
                              kalla_url="plenum_radata_2022_2026"))
    return ut


def main(argv=None):
    p = argparse.ArgumentParser()
    p.add_argument("csv", nargs="+")
    p.add_argument("--out", default="data/legacy.jsonl")
    p.add_argument("--supabase", action="store_true")
    p.add_argument("--kallor", default="config/kallor.csv")
    a = p.parse_args(argv)
    try:
        from .kallor import las_kallor
        NAMN2SLUG.update({k.organisation: k.org_slug for k in las_kallor(a.kallor, bara_aktiva=False)})
    except FileNotFoundError:
        pass
    obs = []
    for path in a.csv:
        with open(path, encoding="utf-8") as f:
            for r in csv.DictReader(f):
                for o in tolka_rad(r):
                    berika(o)
                    if o.efternamn:
                        obs.append(o)
    # dedupe
    uniq = {}
    for o in obs:
        uniq.setdefault(o.nyckel(), o)
    obs = list(uniq.values())
    skriv_jsonl(a.out, obs)
    print(f"{len(obs)} unika uppdrag -> {a.out}")
    if a.supabase:
        from collections import defaultdict
        from .kallor import las_kallor
        from .store import Lager
        lager = Lager.fran_env()

        # 1. Fyll organisationer från config/kallor.csv (alla 311)
        kallor = las_kallor(a.kallor, bara_aktiva=False)
        lager.synka_organisationer(kallor)
        kanda = {k.org_slug for k in kallor}

        # 2. Organisationer som bara finns i rådatan (namnet skiljer sig från listan)
        #    skapas med namnet från rådatan så att inget tappas. Fixa namnet i kallor.csv senare.
        per_org, orgnamn = defaultdict(list), {}
        for o in obs:
            per_org[o.org_slug].append(o)
        for path in a.csv:
            with open(path, encoding="utf-8") as f:
                for r in csv.DictReader(f):
                    n = (r.get("kom_name") or "").strip()
                    if n:
                        orgnamn.setdefault(org_slug_for(n), n)
        saknade = [s for s in per_org if s not in kanda]
        if saknade:
            print("Skapar organisationer som saknas i kallor.csv:", saknade)
            lager.synka_organisationer([
                Kalla(org_slug=s, organisation=orgnamn.get(s, s), kommunkod="",
                      typ="region" if "region" in s else "kommun", system="", adapter="manual",
                      base_url="", aktiv=False, kommentar="Skapad av historikimport: namn från rådata, matcha mot kallor.csv")
                for s in saknade])

        # 3. Spara uppdragen
        for slug, lst in per_org.items():
            k = Kalla(org_slug=slug, organisation=orgnamn.get(slug, slug), kommunkod="", typ="kommun",
                      system="", adapter="", base_url="")
            kid = lager.starta_korning(slug)
            res = lager.spara(k, lst, kid, mandatperiod="2022-2026")
            lager.avsluta_korning(kid, **res)
            print(slug, res)


if __name__ == "__main__":
    main()
