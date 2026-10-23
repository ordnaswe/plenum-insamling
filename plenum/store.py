"""Lagring i Supabase med upsert och historik.

Princip per körning och organisation:
  * Skapa korningar-rad (status 'pagar').
  * Upsert organ, personer, uppdrag med senast_sedd = idag.
  * Säkringsregel: om antalet observerade uppdrag är < SAKRING (standard 60 %)
    av antalet aktiva uppdrag i databasen, avsluta INGET utan markera körningen
    'skippad_sakring'. Det skyddar mot att en halvt laddad sida raderar en
    kommun. Nya uppdrag sparas ändå.
  * Annars: aktiva uppdrag som inte sågs i dag får avslutad = idag, aktiv = false.
  * Varje ny/avslutad post loggas i forandringar.
  * Rådata (JSONL) laddas upp till bucket 'ravdata' om PLENUM_RAVDATA=1.

Kör med --dry-run för att skriva JSONL lokalt utan Supabase.
"""
from __future__ import annotations
import datetime as dt
import json
import logging
import os

from .models import Observation, Kalla
from .normalize import ROLL_RANG

log = logging.getLogger("plenum.store")
SAKRING = float(os.getenv("PLENUM_SAKRING", "0.6"))
BATCH = 500


def _chunks(xs, n=BATCH):
    for i in range(0, len(xs), n):
        yield xs[i:i + n]


class Lager:
    def __init__(self, client=None):
        self.sb = client

    @classmethod
    def fran_env(cls):
        from supabase import create_client
        url = os.environ["SUPABASE_URL"]
        key = os.environ["SUPABASE_SERVICE_KEY"]
        return cls(create_client(url, key))

    # ---- organisationer från kallor.csv ----
    def synka_organisationer(self, kallor: list[Kalla]):
        rader = [dict(org_slug=k.org_slug, namn=k.organisation, kommunkod=k.kommunkod, typ=k.typ,
                      system=k.system, adapter=k.adapter, base_url=k.base_url, aktiv=k.aktiv,
                      kommentar=k.kommentar, uppdaterad=dt.datetime.utcnow().isoformat())
                 for k in kallor]
        unika = {r["org_slug"]: r for r in rader}   # dubbletter i samma batch stoppar upsert
        for c in _chunks(list(unika.values())):
            self.sb.table("organisationer").upsert(c, on_conflict="org_slug").execute()

    # ---- körning ----
    def starta_korning(self, org_slug: str) -> int:
        r = self.sb.table("korningar").insert({"org_slug": org_slug}).execute()
        return r.data[0]["id"]

    def avsluta_korning(self, kid: int, **falt):
        falt["avslutad"] = dt.datetime.utcnow().isoformat()
        self.sb.table("korningar").update(falt).eq("id", kid).execute()

    # ---- huvudflöde ----
    def spara(self, kalla: Kalla, obs: list[Observation], kid: int, mandatperiod: str | None = None) -> dict:
        idag = dt.date.today().isoformat()
        org = kalla.org_slug
        uppdrag_obs = [o for o in obs if o.organ_namn]        # riktiga uppdrag
        epost_obs = [o for o in obs if not o.organ_namn and o.epost]  # personsidor (bara e-post)

        # organ
        organ_rader = {}
        for o in uppdrag_obs:
            organ_rader.setdefault(o.organ_norm, dict(org_slug=org, organ_norm=o.organ_norm, namn=o.organ_namn,
                                                       organ_typ=o.organ_typ, extern_id=o.extern_organ_id or None,
                                                       kalla_url=o.kalla_url, senast_sedd=idag, aktiv=True))
        for c in _chunks(list(organ_rader.values())):
            self.sb.table("organ").upsert(c, on_conflict="org_slug,organ_norm").execute()
        organ_id = {}
        for c in _chunks(list(organ_rader.keys())):
            r = self.sb.table("organ").select("id,organ_norm").eq("org_slug", org).in_("organ_norm", c).execute()
            organ_id.update({x["organ_norm"]: x["id"] for x in r.data})

        # personer (upsert; epost bara om vi faktiskt såg en)
        bef = {x["person_nyckel"]: x for x in self.sb.table("personer")
               .select("person_nyckel,epost,parti").eq("org_slug", org).execute().data}
        pers = {}
        for o in uppdrag_obs + epost_obs:
            pk = o.person_nyckel()
            rad = pers.setdefault(pk, dict(person_nyckel=pk, org_slug=org, fornamn=o.fornamn, efternamn=o.efternamn,
                                           namn_raw=o.namn_raw, namn_osakert=o.namn_osakert,
                                           parti=o.parti, parti_raw=o.parti_raw, senast_sedd=idag, aktiv=True))
            if o.epost:
                rad.update(epost=o.epost, epost_kalla_url=o.kalla_url, epost_sedd=idag)
            if not rad.get("parti") and o.parti:
                rad.update(parti=o.parti, parti_raw=o.parti_raw)
        nya_personer = [pk for pk in pers if pk not in bef]
        nya_epost = [pk for pk, r in pers.items() if r.get("epost") and bef.get(pk, {}).get("epost") != r["epost"]]
        for c in _chunks(list(pers.values())):
            self.sb.table("personer").upsert(c, on_conflict="person_nyckel").execute()

        # uppdrag
        aktiva = {x["uppdrag_nyckel"] for x in self.sb.table("uppdrag").select("uppdrag_nyckel")
                  .eq("org_slug", org).eq("aktiv", True).execute().data}
        rader, sedda = [], set()
        for o in uppdrag_obs:
            uk = o.nyckel()
            if uk in sedda:
                continue
            sedda.add(uk)
            rader.append(dict(uppdrag_nyckel=uk, person_nyckel=o.person_nyckel(), organ_id=organ_id[o.organ_norm],
                              org_slug=org, roll=o.roll, roll_raw=o.roll_raw, roll_rang=ROLL_RANG.get(o.roll, 99),
                              kalla_url=o.kalla_url, mandatperiod=o.mandatperiod or mandatperiod, senast_sedd=idag,
                              aktiv=True, avslutad=None))
        datum = {o.nyckel(): (o.start_datum, o.slut_datum) for o in uppdrag_obs if o.start_datum}
        med, utan = [], []
        for r in rader:
            d = datum.get(r["uppdrag_nyckel"])
            if d:
                med.append(dict(r, start_datum=d[0], slut_datum=d[1] or None))
            else:
                utan.append(r)
        for c in _chunks(utan):
            self.sb.table("uppdrag").upsert(c, on_conflict="uppdrag_nyckel").execute()
        for c in _chunks(med):
            self.sb.table("uppdrag").upsert(c, on_conflict="uppdrag_nyckel").execute()
        nya = [r["uppdrag_nyckel"] for r in rader if r["uppdrag_nyckel"] not in aktiva]

        # avsluta det som försvann, med säkring
        forsvunna = [uk for uk in aktiva if uk not in sedda]
        status = "ok"
        if aktiva and len(sedda) < SAKRING * len(aktiva):
            status = "skippad_sakring"
            log.warning("%s: bara %d av %d aktiva sedda, avslutar inget", org, len(sedda), len(aktiva))
            forsvunna = []
        elif not sedda:
            status = "tom"
            forsvunna = []
        for c in _chunks(forsvunna):
            self.sb.table("uppdrag").update({"aktiv": False, "avslutad": idag}).in_("uppdrag_nyckel", c).execute()

        # förändringslogg
        logg = ([dict(org_slug=org, typ="nytt_uppdrag", uppdrag_nyckel=uk) for uk in nya]
                + [dict(org_slug=org, typ="avslutat_uppdrag", uppdrag_nyckel=uk) for uk in forsvunna]
                + [dict(org_slug=org, typ="ny_person", person_nyckel=pk) for pk in nya_personer]
                + [dict(org_slug=org, typ="ny_epost", person_nyckel=pk, detaljer={"epost": pers[pk]["epost"]}) for pk in nya_epost])
        for c in _chunks(logg):
            self.sb.table("forandringar").insert(c).execute()

        return dict(status=status, antal_uppdrag=len(sedda), antal_nya=len(nya), antal_avslutade=len(forsvunna))

    def ladda_upp_ravdata(self, org_slug: str, obs: list[Observation]) -> str | None:
        if os.getenv("PLENUM_RAVDATA", "0") != "1":
            return None
        path = f"{dt.date.today().isoformat()}/{org_slug}.jsonl"
        data = "\n".join(json.dumps(o.to_dict(), ensure_ascii=False) for o in obs).encode("utf-8")
        self.sb.storage.from_("ravdata").upload(path, data, {"content-type": "application/x-ndjson", "upsert": "true"})
        return path


def skriv_jsonl(path: str, obs: list[Observation]):
    os.makedirs(os.path.dirname(path) or ".", exist_ok=True)
    with open(path, "w", encoding="utf-8") as f:
        for o in obs:
            f.write(json.dumps(o.to_dict(), ensure_ascii=False) + "\n")
