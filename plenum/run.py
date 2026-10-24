"""Kör insamlingen.

  python -m plenum.run --org haninge --dry-run          # en organisation, skriv data/out/haninge.jsonl
  python -m plenum.run --shard 0/6                      # var sjätte organisation, spara i Supabase
  python -m plenum.run --adapter troman --dry-run       # alla Troman-kunder

Miljövariabler: SUPABASE_URL, SUPABASE_SERVICE_KEY, PLENUM_BROWSER, PLENUM_PROXY,
PLENUM_PERSONSIDOR, PLENUM_RAVDATA, PLENUM_SAKRING, PLENUM_MIN_PAUS, PLENUM_MAX_PAUS.
"""
from __future__ import annotations
import argparse
import logging
import sys
import time
import traceback

from .adapters import skapa
from .fetch import Hamtare, Blockerad
from .adapters.troman import InaktuellKalla
from .kallor import las_kallor
from .store import Lager, skriv_jsonl

log = logging.getLogger("plenum")


def valj(kallor, args):
    if args.org:
        kallor = [k for k in kallor if k.org_slug in set(args.org)]
    if args.adapter:
        kallor = [k for k in kallor if k.adapter == args.adapter]
    if args.shard:
        i, n = map(int, args.shard.split("/"))
        kallor = [k for j, k in enumerate(sorted(kallor, key=lambda k: k.org_slug)) if j % n == i]
    return kallor


def main(argv=None):
    p = argparse.ArgumentParser()
    p.add_argument("--kallor", default="config/kallor.csv")
    p.add_argument("--org", action="append")
    p.add_argument("--adapter")
    p.add_argument("--shard", help="i/n")
    p.add_argument("--dry-run", action="store_true", help="skriv JSONL lokalt, rör inte Supabase")
    p.add_argument("--out", default="data/out")
    p.add_argument("--synka-org", action="store_true", help="upsert organisationer från kallor.csv först")
    p.add_argument("-v", action="store_true")
    args = p.parse_args(argv)
    logging.basicConfig(level=logging.DEBUG if args.v else logging.INFO,
                        format="%(asctime)s %(levelname)s %(name)s: %(message)s")

    kallor = valj(las_kallor(args.kallor), args)
    log.info("%d organisationer att köra", len(kallor))
    lager = None if args.dry_run else Lager.fran_env()
    if lager and args.synka_org:
        lager.synka_organisationer(las_kallor(args.kallor, bara_aktiva=False))

    misslyckade = 0
    with Hamtare() as h:
        for k in kallor:
            t0 = time.time()
            fore = h.antal_hamtningar
            kid = lager.starta_korning(k.org_slug) if lager else None
            try:
                adapter = skapa(k, h)
                obs = adapter.kor()
                if k.adapter == "manual":
                    res = dict(status="ingen_kalla", antal_uppdrag=0)
                elif args.dry_run:
                    skriv_jsonl(f"{args.out}/{k.org_slug}.jsonl", obs)
                    res = dict(status="ok" if obs else "tom", antal_uppdrag=len(obs))
                else:
                    res = lager.spara(k, obs, kid)
                    res["ravdata_path"] = lager.ladda_upp_ravdata(k.org_slug, obs)
                log.info("%s: %s, %d uppdrag, %d hämtningar, %.0fs", k.org_slug, res["status"],
                         res["antal_uppdrag"], h.antal_hamtningar - fore, time.time() - t0)
            except InaktuellKalla as e:
                res = dict(status="inaktuell_kalla", felmeddelande=str(e))
                log.warning("%s: %s", k.org_slug, e)
            except Blockerad as e:
                res = dict(status="blockerad", felmeddelande=str(e))
                misslyckade += 1
                log.error("%s blockerad: %s", k.org_slug, e)
            except Exception as e:
                res = dict(status="fel", felmeddelande=f"{e}\n{traceback.format_exc()[-1500:]}")
                misslyckade += 1
                log.exception("%s fel", k.org_slug)
            if lager:
                lager.avsluta_korning(kid, antal_hamtningar=h.antal_hamtningar - fore, **res)
    return 1 if misslyckade and misslyckade == len(kallor) else 0


if __name__ == "__main__":
    sys.exit(main())
