"""Provkör generic_table i autoläge på kommuner med egen webbplats (config/egna_sajter.csv,
framtagen ur kartläggningen) och föreslår vilka som kan kopplas in.

  python -m plenum.provkor_egna                  # provkör alla, skriv data/provkorning_egna.csv
  python -m plenum.provkor_egna --org boden      # en kommun
  python -m plenum.provkor_egna --koppla-in      # läs rapporten, koppla in de godkända i kallor.csv

Inget skrivs till Supabase. Godkänd = minst 40 uppdrag, minst 70 % med igenkänt parti, minst 50 % med roll,
minst ett organ med 10 personer eller fler och inga organnamn som ser ut som skräp
(kakbanner, "Skriv ut", kommunens namn osv). Allt annat lämnas som manual.
"""
from __future__ import annotations
import argparse
import csv
import json
import os
import time
from collections import Counter

from .adapters.generic_table import GenericTableAdapter
from .fetch import Hamtare
from .models import Kalla
from .normalize import PARTIER

RAPPORT = "data/provkorning_egna.csv"
FALT = ["org_slug", "organisation", "start_url", "antal_uppdrag", "antal_organ", "antal_personer",
        "andel_parti", "andel_roll", "storsta_organ", "exempel", "godkand", "orsak"]


def bedom(obs) -> dict:
    if not obs:
        return dict(antal_uppdrag=0, godkand=0, orsak="inga uppdrag hittades")
    organ = Counter(o.organ_namn for o in obs)
    pers = {(o.fornamn, o.efternamn) for o in obs}
    parti = sum(1 for o in obs if o.parti in PARTIER or (o.parti and len(o.parti) > 3)) / len(obs)
    roll = sum(1 for o in obs if o.roll != "ovrigt") / len(obs)
    storsta, n_storsta = organ.most_common(1)[0]
    orsak = []
    if len(obs) < 40:
        orsak.append("färre än 40 uppdrag")
    if parti < 0.7:
        orsak.append(f"bara {parti:.0%} med parti")
    if n_storsta < 10:
        orsak.append("inget organ med minst 10 personer")
    if roll < 0.5:
        orsak.append(f"bara {roll:.0%} med roll")
    from .adapters.generic_table import SKRAP_RUBRIK
    skrap = [o for o in organ if SKRAP_RUBRIK.search(o)]
    if skrap:
        orsak.append("misstänkta organnamn: " + "; ".join(skrap[:3]))
    ex = "; ".join(f"{o.fornamn} {o.efternamn} ({o.parti}) {o.roll} i {o.organ_namn}" for o in obs[:3])
    return dict(antal_uppdrag=len(obs), antal_organ=len(organ), antal_personer=len(pers),
                andel_parti=f"{parti:.2f}", andel_roll=f"{roll:.2f}",
                storsta_organ=f"{storsta} ({n_storsta})", exempel=ex,
                godkand=0 if orsak else 1, orsak=", ".join(orsak))


def provkor(args):
    from . import fetch as _f
    _f.MIN_PAUS, _f.MAX_PAUS = 0.8, 1.6
    sajter = list(csv.DictReader(open(args.egna, encoding="utf-8-sig")))
    if args.org:
        sajter = [s for s in sajter if s["org_slug"] in set(args.org)]
    rader = []
    with Hamtare(browser_fallback=False) as h:
        for s in sajter:
            k = Kalla(org_slug=s["org_slug"], organisation=s["organisation"], kommunkod="",
                      typ=s.get("typ") or "kommun", system="egen", adapter="generic_table",
                      base_url=s["start_url"], extra={"auto": True})
            t0 = time.time()
            try:
                obs = GenericTableAdapter(k, h).kor()
                r = bedom(obs)
            except Exception as e:
                r = dict(antal_uppdrag=0, godkand=0, orsak=f"fel: {e}"[:200])
            r.update(org_slug=s["org_slug"], organisation=s["organisation"], start_url=s["start_url"])
            rader.append(r)
            print(f"{'OK ' if r['godkand'] else '-- '} {s['organisation']:24s} {r.get('antal_uppdrag',0):5} uppdrag "
                  f"{r.get('antal_organ','')!s:>3} organ  parti {r.get('andel_parti','')}  roll {r.get('andel_roll','')}  "
                  f"{r.get('orsak','')}  ({time.time()-t0:.0f}s)")
    os.makedirs("data", exist_ok=True)
    with open(args.rapport, "w", encoding="utf-8", newline="") as f:
        w = csv.DictWriter(f, fieldnames=FALT, extrasaction="ignore")
        w.writeheader()
        w.writerows(rader)
    ok = [r for r in rader if r["godkand"]]
    print(f"\n{len(ok)} av {len(rader)} godkända, totalt {sum(int(r['antal_uppdrag']) for r in ok)} uppdrag -> {args.rapport}")


def koppla_in(args):
    rapport = [r for r in csv.DictReader(open(args.rapport, encoding="utf-8-sig")) if r["godkand"] == "1"]
    per = {r["org_slug"]: r for r in rapport}
    alla = list(csv.DictReader(open(args.kallor, encoding="utf-8-sig")))
    n = 0
    for r in alla:
        t = per.get(r["org_slug"])
        if t and r.get("adapter") == "manual":
            r.update(system="egen", adapter="generic_table", base_url=t["start_url"], aktiv="1",
                     extra=json.dumps({"auto": True}),
                     kommentar=f"Egen webbplats, provkörd {time.strftime('%Y-%m-%d')}: {t['antal_uppdrag']} uppdrag")
            n += 1
            print(f"  KOPPLAD {r['organisation']} -> {t['start_url']}")
    with open(args.kallor, "w", encoding="utf-8", newline="") as f:
        w = csv.DictWriter(f, fieldnames=alla[0].keys())
        w.writeheader()
        w.writerows(alla)
    print(f"{n} rader inkopplade i {args.kallor}")


def main(argv=None):
    p = argparse.ArgumentParser()
    p.add_argument("--egna", default="config/egna_sajter.csv")
    p.add_argument("--kallor", default="config/kallor.csv")
    p.add_argument("--rapport", default=RAPPORT)
    p.add_argument("--org", action="append")
    p.add_argument("--koppla-in", action="store_true")
    a = p.parse_args(argv)
    koppla_in(a) if a.koppla_in else provkor(a)


if __name__ == "__main__":
    main()
