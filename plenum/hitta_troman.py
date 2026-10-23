"""Hittar vilka kommuner/regioner som har en Troman Publik-sajt genom att prova
<kandidat>.tromanpublik.se för varje organisation i config/kallor.csv.

  python -m plenum.hitta_troman                 # skriver data/troman_funna.csv
  python -m plenum.hitta_troman --uppdatera     # skriver dessutom in träffarna i config/kallor.csv

Träff = HTTP 200 och titeln innehåller "Förtroendevalda". Kandidater per organisation:
slug med och utan bindestreck, plus några varianter för regioner. Kunder med egen
domän (t.ex. politiker.goteborg.se) hittas inte här utan måste läggas in för hand.
"""
from __future__ import annotations
import argparse
import csv
import os
import re
import time

from .kallor import las_kallor, slugga
from .fetch import Hamtare

MIN_PAUS = 0.3

# vanliga kortformer som regionerna själva använder i domäner
KANDA_FORKORTNINGAR = {
    "vastra-gotalandsregionen": ["vgregion", "vgr", "vastragotaland", "regionvastragotaland"],
    "region-jonkoping": ["rjl", "regionjonkopingslan"],
    "region-jamtland": ["rjh", "regionjh", "jamtlandharjedalen", "regionjamtlandharjedalen"],
    "region-vasternorrland": ["rvn"],
    "region-orebro": ["regionorebrolan", "orebrolan"],
    "region-kalmar": ["regionkalmarlan", "ltkalmar"],
    "region-uppsala": ["lul"],
    "region-vastmanland": ["ltv"],
    "region-sormland": ["dll", "sormland", "sodermanland"],
    "region-stockholm": ["sll", "regionstockholm"],
    "region-skane": ["skane"],
    "region-gavleborg": ["lg", "regiongavleborg"],
    "region-norrbotten": ["nll"],
    "region-vasterbotten": ["vll"],
    "region-dalarna": ["ltdalarna"],
    "region-halland": ["regionhalland"],
    "region-kronoberg": ["ltkronoberg"],
    "region-blekinge": ["ltblekinge"],
    "region-varmland": ["liv", "regionvarmland"],
    "region-ostergotland": ["lio", "regionostergotland"],
    "region-gotland": ["gotland"],
}


def kandidater(namn: str, slug: str, typ: str) -> list[str]:
    s = slugga(namn)
    ut = [s, s.replace("-", "")]
    if typ == "region":
        bas = re.sub(r"^region-?", "", s).replace("-lan", "").replace("regionen", "").replace("-", "")
        baser = {bas, re.sub(r"s$", "", bas)}          # jonkopings -> jonkoping
        for b in baser:
            ut += [b, f"region{b}", f"region-{b}", f"region{b}lan", f"{b}region", f"rk{b}",
                   f"lt{b}", f"landstinget{b}", f"regionen{b}"]
        ut += [k for k in KANDA_FORKORTNINGAR.get(slug, [])]
    if slug not in ut:
        ut.append(slug)
    sedda, res = set(), []
    for k in ut:
        k = k.strip("-")
        if k and k not in sedda:
            sedda.add(k)
            res.append(k)
    return res


def bedom(status: int, titel: str, har_org_lankar: bool, typ: str) -> tuple[bool, str]:
    """Träff om sidan svarar 200 och ser ut som Troman (titel ELLER länkar till /organisation/).
    Okända subdomäner svarar 500, men vi kräver ändå ett Troman-kännetecken.
    En region får inte matcha en sida vars titel säger 'kommun' (Kalmar/Örebro-fallet)."""
    if status != 200:
        return False, f"status {status}"
    t = titel.lower()
    if not ("förtroendevalda" in t or har_org_lankar):
        return False, f"200 men inget Troman-kännetecken (titel: {titel!r})"
    if typ == "region" and "kommun" in t and "region" not in t:
        return False, f"kommunsajt, inte region (titel: {titel!r})"
    return True, ""


def main(argv=None):
    p = argparse.ArgumentParser()
    p.add_argument("--kallor", default="config/kallor.csv")
    p.add_argument("--out", default="data/troman_funna.csv")
    p.add_argument("--uppdatera", action="store_true")
    a = p.parse_args(argv)
    os.environ.setdefault("PLENUM_MIN_PAUS", str(MIN_PAUS))
    os.environ.setdefault("PLENUM_MAX_PAUS", str(MIN_PAUS + 0.3))
    from . import fetch as _f
    _f.MIN_PAUS, _f.MAX_PAUS = MIN_PAUS, MIN_PAUS + 0.3

    kallor = las_kallor(a.kallor, bara_aktiva=False)
    funna, saknas = [], []
    with Hamtare(browser_fallback=False) as h:
        for k in kallor:
            traff = None
            for kand in kandidater(k.organisation, k.org_slug, k.typ):
                url = f"https://{kand}.tromanpublik.se/"
                try:
                    r = h._session.get(url)   # direkt, utan robots/paus-logik: en förfrågan per kandidat
                    time.sleep(MIN_PAUS)
                except Exception:
                    continue
                titel = (r.css("title::text").get() or "").strip() if r.status == 200 else ""
                har_org = r.status == 200 and any("/organisation/" in (x or "") for x in r.css("a::attr(href)").getall())
                ok, varfor = bedom(r.status, titel, har_org, k.typ)
                if ok:
                    traff = (url, titel or "(ingen titel)")
                    break
                if r.status == 200:
                    print(f"  avvisad {url}: {varfor}")
            if traff:
                funna.append(dict(org_slug=k.org_slug, organisation=k.organisation, typ=k.typ,
                                  base_url=traff[0], titel=traff[1], redan_i_kallor=k.adapter == "troman"))
                print(f"TRÄFF   {k.organisation:28s} {traff[0]}   ({traff[1]})")
            else:
                saknas.append(k)
                print(f"-       {k.organisation}")

    os.makedirs(os.path.dirname(a.out) or ".", exist_ok=True)
    with open(a.out, "w", encoding="utf-8", newline="") as f:
        w = csv.DictWriter(f, fieldnames=["org_slug", "organisation", "typ", "base_url", "titel", "redan_i_kallor"])
        w.writeheader()
        w.writerows(funna)
    print(f"\n{len(funna)} Troman-sajter funna ({sum(1 for x in funna if not x['redan_i_kallor'])} nya), "
          f"{len(saknas)} organisationer utan träff. -> {a.out}")

    if a.uppdatera:
        rader = list(csv.DictReader(open(a.kallor, encoding="utf-8")))
        uppdatera_kallor(rader, funna, time.strftime("%Y-%m-%d"))
        with open(a.kallor, "w", encoding="utf-8", newline="") as f:
            w = csv.DictWriter(f, fieldnames=rader[0].keys())
            w.writeheader()
            w.writerows(rader)


AUTO = "Troman, hittad automatiskt"


def uppdatera_kallor(rader: list[dict], funna: list[dict], idag: str) -> None:
    """Regler:
    * Träff på en rad som inte är Troman -> sätt Troman.
    * Automatiskt satt rad utan träff i dag -> tillbaka till manual (rättar falska träffar).
    * Automatiskt satt rad med ny URL -> uppdatera URL.
    * Handinlagd Troman-rad utan träff -> behålls men flaggas KONTROLLERA.
    * Två rader med samma sajt -> den vars typ titeln nämner behålls, den andra inaktiveras.
    """
    per_slug = {x["org_slug"]: x for x in funna}
    andr = []
    for r in rader:
        t = per_slug.get(r["org_slug"])
        auto = (r.get("kommentar") or "").startswith(AUTO)
        if t:
            if r.get("adapter") != "troman" or (auto and r.get("base_url") != t["base_url"]):
                r.update(system="troman", adapter="troman", base_url=t["base_url"], aktiv="1",
                         kommentar=f"{AUTO} {idag}: {t['titel']}")
                andr.append(f"SATT     {r['organisation']} -> {t['base_url']}")
        elif r.get("adapter") == "troman":
            if auto:
                r.update(system="", adapter="manual", base_url="", aktiv="1",
                         kommentar=f"Tidigare falsk Troman-träff, återställd {idag}")
                andr.append(f"ÅTERSTÄLLD {r['organisation']} (ingen giltig Troman-sajt)")
            elif "KONTROLLERA" not in (r.get("kommentar") or ""):
                r["kommentar"] = f"KONTROLLERA: svarade inte som Troman {idag}. " + (r.get("kommentar") or "")
                andr.append(f"KONTROLLERA {r['organisation']} {r.get('base_url')}")
    # dubbletter: samma base_url på flera aktiva rader
    per_url: dict[str, list[dict]] = {}
    for r in rader:
        if r.get("adapter") == "troman" and r.get("aktiv") == "1" and r.get("base_url"):
            per_url.setdefault(r["base_url"], []).append(r)
    for url, grupp in per_url.items():
        if len(grupp) < 2:
            continue
        titel = (per_slug.get(grupp[0]["org_slug"]) or per_slug.get(grupp[1]["org_slug"]) or {}).get("titel", "").lower()
        behall_typ = "region" if "region" in titel else "kommun"
        behall = next((r for r in grupp if r["typ"] == behall_typ), grupp[0])
        for r in grupp:
            if r is not behall:
                r.update(aktiv="0", kommentar=f"Samma sajt som {behall['organisation']} ({url}), inaktiverad {idag}")
                andr.append(f"DUBBLETT {r['organisation']} inaktiverad, {behall['organisation']} behålls")
    print("\nÄndringar i kallor.csv:")
    for x in andr:
        print("  ", x)
    print(f"{len(andr)} ändringar")


if __name__ == "__main__":
    main()
