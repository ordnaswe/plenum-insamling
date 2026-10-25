"""Kartlägger organisationer utan känd källa (adapter = manual i config/kallor.csv).

För varje organisation:
  1. Hittar webbplatsen (kända adresser, annars www.<namn>.se och varianter).
     Godkänns bara om organisationens namn står i titeln eller i början av sidan.
  2. Följer länkar som ser ut att leda till förtroendevalda/politik (högst ~8 sidor).
  3. Mäter på varje sida hur mycket den liknar en politikerlista: partibeteckningar
     som (S) och (M), orden ledamot/ersättare, mailto-länkar.
  4. Letar efter kända systems kännetecken i HTML och länkar (Troman, Meetings Plus,
     Netpublicator, InsynSverige, Ciceron, SiteVision, Episerver ...).

Resultat: data/kartlaggning.csv. Inget skrivs till Supabase eller kallor.csv.
Fingeravtrycken redovisas som det som faktiskt hittades i koden, inte som slutsatser.

  python -m plenum.kartlagg                 # alla manual-rader
  python -m plenum.kartlagg --org solna     # en
"""
from __future__ import annotations
import argparse
import csv
import os
import re
from collections import Counter
from urllib.parse import urljoin, urlparse, unquote

from .fetch import Hamtare
from .kallor import las_kallor, slugga

# Webbplatser där namnet inte ger adressen. Bara adresser som är allmänt kända;
# allt annat provas fram och verifieras mot sidans innehåll.
KANDA = {
    "region-stockholm": "https://www.regionstockholm.se/",
    "region-skane": "https://www.skane.se/",
    "region-sormland": "https://regionsormland.se/",
    "region-jonkoping": "https://www.rjl.se/",
    "region-kronoberg": "https://www.regionkronoberg.se/",
    "region-kalmar": "https://regionkalmar.se/",
    "region-orebro": "https://www.regionorebrolan.se/",
    "region-dalarna": "https://www.regiondalarna.se/",
}

NYCKELORD = [  # (mönster, vikt) för länktext + adress
    (r"förtroendevald", 10), (r"fortroendevald", 10), (r"våra politiker|vara-politiker", 10),
    (r"sök politiker|hitta politiker|politikerregister", 10), (r"politiker", 8),
    (r"kommunfullmäktige|regionfullmäktige|kommunfullmaktige|regionfullmaktige", 5),
    (r"nämnder|namnder", 5), (r"kontakta politiker", 8), (r"politisk organisation", 6),
    (r"kommun och politik|kommun-och-politik|politik och demokrati|demokrati", 3),
    (r"politik", 4), (r"styrelser|bolag", 2), (r"organisation", 1),
]
NEGATIVA = r"protokoll|kallelse|sammanträdesdatum|valet|röst|valresultat|lediga jobb|cookie|press"

FINGERAVTRYCK = [  # (namn, mönster i HTML/länkar)
    ("troman", r"tromanpublik\.se|troman\.se"),
    ("meetingsplus", r"meetingsplus"),
    ("netpublicator", r"netpublicator"),
    ("insynsverige", r"insynsverige"),
    ("ciceron", r"ciceron"),
    ("platina", r"platina"),
    ("lex", r"lexwebb|lex\.\w+\.se"),
    ("evald", r"evald\."),
    ("politikerportal", r"politikerportal|politiker\.\w+\.se|politik\.\w+\.se"),
    ("sitevision", r"sitevision|/sv-|sv-portlet|sv-layout"),
    ("episerver", r"episerver|optimizely|epi-"),
    ("wordpress", r"wp-content|wordpress"),
    ("drupal", r"drupal"),
]
_FA = [(n, re.compile(p, re.I)) for n, p in FINGERAVTRYCK]
_PARTI = re.compile(
    r"\((S|M|SD|C|V|KD|L|MP)\)"
    r"|socialdemokraterna|moderaterna|sverigedemokraterna|centerpartiet|vänsterpartiet"
    r"|kristdemokraterna|liberalerna|miljöpartiet", re.I)
_BRA_URL = re.compile(r"ledamot|ledamöter|ledamoter|fortroendevald|förtroendevald|politiker", re.I)
_ROLL = re.compile(r"\b(ledamot|ersättare|ordförande)\b", re.I)


def _text(el) -> str:
    try:
        return re.sub(r"\s+", " ", el.get_all_text(strip=True) or "").strip()
    except Exception:
        return ""


def _html(page) -> str:
    try:
        return page.html_content or ""
    except Exception:
        return (page.body or b"").decode("utf-8", "ignore")


def kandidater(k) -> list[str]:
    ut = []
    if (k.extra or {}).get("hemsida"):
        ut.append(k.extra["hemsida"])
    if k.org_slug in KANDA:
        ut.append(KANDA[k.org_slug])
    s = slugga(k.organisation)
    for bas in dict.fromkeys([s, s.replace("-", "")]):
        ut += [f"https://www.{bas}.se/", f"https://{bas}.se/", f"https://www.{bas}kommun.se/"]
    return list(dict.fromkeys(ut))


def namn_kort(k) -> str:
    n = re.sub(r"^region\s+", "", k.organisation, flags=re.I)
    n = re.sub(r"\s+län$", "", n, flags=re.I)
    return n.lower()


def ar_ratt_sajt(page, k) -> bool:
    titel = (page.css("title::text").get() or "").lower()
    början = _text(page)[:5000].lower() if page.css("body") else ""
    n = namn_kort(k)
    return n in titel or f"{n} kommun" in början or f"{n}s kommun" in början or f"region {n}" in början


def poang_lank(text: str, href: str) -> int:
    t = f"{text} {unquote(href)}".lower()
    if re.search(NEGATIVA, t):
        return 0
    return sum(v for p, v in NYCKELORD if re.search(p, t))


def sidsignal(page) -> tuple[int, int, int]:
    # alt-texter räknas med: vissa sajter visar partiet bara som logotyp
    alt = " ".join(x for x in page.css("img::attr(alt)").getall() if x)
    txt = _text(page) + " " + alt
    mail = sum(1 for h in page.css("a::attr(href)").getall() if h and h.lower().startswith("mailto:"))
    return len(_PARTI.findall(txt)), len(_ROLL.findall(txt)), mail


def fingeravtryck(html: str, lankar: list[str]) -> set[str]:
    blob = html + " " + " ".join(lankar)
    return {n for n, rx in _FA if rx.search(blob)}


def kartlagg_en(h, k, max_sidor: int = 8) -> dict:
    rad = dict(org_slug=k.org_slug, organisation=k.organisation, typ=k.typ, hemsida="",
               basta_sida="", parti_traffar=0, roll_traffar=0, mailto=0,
               fingeravtryck="", extern_systemlank="", inbaddat="", sidor_404=0, besokta_sidor=0, anteckning="")
    start = None
    for url in kandidater(k):
        try:
            r = h.get(url)
        except Exception:
            continue
        if r.status == 200 and ar_ratt_sajt(r, k):
            start = r
            break
    if start is None:
        rad["anteckning"] = "hittade ingen webbplats som matchar namnet"
        return rad
    rad["hemsida"] = start.url
    host = urlparse(start.url).netloc.replace("www.", "")

    fa: set[str] = set()
    extern = ""
    basta = (-1, None, (0, 0, 0))
    ko = [(100, start.url, start)]
    sedda = {start.url}
    besokta = 0
    noll404 = 0
    iframes: set[str] = set()
    while ko and besokta < max_sidor:
        ko.sort(key=lambda x: -x[0])
        _, url, page = ko.pop(0)
        if page is None:
            try:
                page = h.get(url)
            except Exception:
                continue
            if page.status != 200:
                continue
        titel = (page.css("title::text").get() or "").lower()
        if "404" in titel or "sidan kunde inte hittas" in titel or "/404" in (page.css('meta[property="og:url"]::attr(content)').get() or ""):
            noll404 += 1
            continue
        besokta += 1
        lankar = [urljoin(url, x) for x in page.css("a::attr(href)").getall() if x]
        for src in page.css("iframe::attr(src)").getall():
            if src and not src.startswith(("about:", "javascript:")):
                iframes.add(urlparse(urljoin(url, src)).netloc)
                lankar.append(urljoin(url, src))
        fa |= fingeravtryck(_html(page), lankar)
        sig = sidsignal(page)
        p = sig[0] * 2 + sig[1] + sig[2] + (3 if _BRA_URL.search(url) else 0)
        if url != start.url and p > basta[0]:
            basta = (p, url, sig)
        for a in page.css("a"):
            href = a.attrib.get("href") or ""
            if not href or href.startswith(("mailto:", "tel:", "javascript:", "#")):
                continue
            u = urljoin(url, href).split("#")[0]
            uhost = urlparse(u).netloc.replace("www.", "")
            sc = poang_lank(_text(a), u)
            if not extern and any(rx.search(u) for n, rx in _FA if n in
                                  ("troman", "meetingsplus", "netpublicator", "insynsverige", "ciceron", "evald", "politikerportal")):
                extern = u
            if sc <= 0 or u in sedda:
                continue
            # följ interna länkar och kända politiksystem på andra domäner
            if uhost.endswith(host) or any(rx.search(u) for _, rx in _FA[:9]):
                sedda.add(u)
                ko.append((sc, u, None))
    # inbäddade tjänster som bara är video/kartor/cookies räknas inte
    iframes = {d for d in iframes if not re.search(r"youtube|vimeo|google|maps|cookie|facebook|twitter|qbrick|readspeaker|siteimprove", d)}
    rad.update(besokta_sidor=besokta, fingeravtryck=",".join(sorted(fa)), extern_systemlank=extern,
               inbaddat=",".join(sorted(iframes)), sidor_404=noll404)
    if basta[1]:
        rad.update(basta_sida=basta[1], parti_traffar=basta[2][0], roll_traffar=basta[2][1], mailto=basta[2][2])
    if not rad["basta_sida"]:
        rad["anteckning"] = "hittade ingen sida om politiker"
    elif basta[0] < 10:
        rad["anteckning"] = ("svag signal; listan verkar vara inbäddad: " + rad["inbaddat"]) if rad["inbaddat"] \
            else "svag signal, listan laddas troligen med JavaScript eller saknas"
    return rad


def main(argv=None):
    p = argparse.ArgumentParser()
    p.add_argument("--kallor", default="config/kallor.csv")
    p.add_argument("--org", action="append")
    p.add_argument("--out", default="data/kartlaggning.csv")
    a = p.parse_args(argv)
    from . import fetch as _f
    _f.MIN_PAUS, _f.MAX_PAUS = 0.8, 1.6
    kallor = [k for k in las_kallor(a.kallor) if k.adapter == "manual"]
    if a.org:
        kallor = [k for k in kallor if k.org_slug in set(a.org)]
    print(f"{len(kallor)} organisationer att kartlägga")
    rader = []
    with Hamtare(browser_fallback=False) as h:
        for k in kallor:
            try:
                rad = kartlagg_en(h, k)
            except Exception as e:
                rad = dict(org_slug=k.org_slug, organisation=k.organisation, typ=k.typ, anteckning=f"fel: {e}")
            rader.append(rad)
            print(f"{k.organisation:28s} {rad.get('hemsida',''):38s} -> {rad.get('basta_sida','')}  "
                  f"[{rad.get('fingeravtryck','')}] P{rad.get('parti_traffar',0)} {rad.get('inbaddat','')} {rad.get('anteckning','')}")
    os.makedirs(os.path.dirname(a.out) or ".", exist_ok=True)
    falt = ["org_slug", "organisation", "typ", "hemsida", "basta_sida", "parti_traffar", "roll_traffar",
            "mailto", "fingeravtryck", "extern_systemlank", "inbaddat", "sidor_404", "besokta_sidor", "anteckning"]
    with open(a.out, "w", encoding="utf-8", newline="") as f:
        w = csv.DictWriter(f, fieldnames=falt, extrasaction="ignore")
        w.writeheader()
        w.writerows(rader)
    fa = Counter(x for r in rader for x in (r.get("fingeravtryck") or "").split(",") if x)
    print("\nSammanfattning")
    print(f"  webbplats hittad: {sum(1 for r in rader if r.get('hemsida'))} av {len(rader)}")
    print(f"  sida med tydlig politikerlista (minst 5 partibeteckningar): "
          f"{sum(1 for r in rader if int(r.get('parti_traffar') or 0) >= 5)}")
    print(f"  länk till externt politiksystem: {sum(1 for r in rader if r.get('extern_systemlank'))}")
    ib = Counter(x for r in rader for x in (r.get("inbaddat") or "").split(",") if x)
    print("  inbäddade tjänster:", ", ".join(f"{n} {c}" for n, c in ib.most_common(15)))
    print("  fingeravtryck:", ", ".join(f"{n} {c}" for n, c in fa.most_common()))
    print(f"-> {a.out}")


if __name__ == "__main__":
    main()
