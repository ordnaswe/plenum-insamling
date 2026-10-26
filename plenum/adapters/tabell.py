"""Heuristisk tolkning av HTML-tabeller och listor med förtroendevalda.

Används av både generic_table-adaptern och Troman-adaptern. Idén: hitta
kolumner via rubriker (Namn/Parti/Uppdrag/E-post) och falla tillbaka på
innehållsmönster om rubriker saknas. Inget gissas; en rad utan igenkänt
namn hoppas över.
"""
from __future__ import annotations
import re

from ..models import Observation
from ..normalize import hitta_epost, normalisera_roll, normalisera_parti, PARTIER, skala_rollprefix, ar_personnamn

RUBRIK = {
    "efternamn": re.compile(r"^efternamn", re.I),
    "fornamn": re.compile(r"^f(ö|o)rnamn", re.I),
    "namn": re.compile(r"^(namn|ledamot|person|förtroendevald|ledamöter)", re.I),
    "parti": re.compile(r"^parti", re.I),
    "roll": re.compile(r"^(uppdrag|roll|funktion|befattning|post)", re.I),
    "epost": re.compile(r"e-?post|mail", re.I),
    "organ": re.compile(r"^(organ|nämnd|styrelse)", re.I),
}
_PARTI_TOKEN = re.compile(r"^\(?(" + "|".join(
    re.escape(a) for v in PARTIER.values() for a in v if len(a) <= 2) + r")\)?$", re.I)
_ROLL_ORD = re.compile(r"ordf|ledamot|ersättare|ersattare|revisor|suppleant|gruppledare|ombud|insyn", re.I)


def _text(el) -> str:
    try:
        return re.sub(r"\s+", " ", el.get_all_text(strip=True) or "").strip()
    except Exception:
        return ""


def _epost_i(el) -> str:
    for href in el.css("a::attr(href)").getall():
        if href and href.lower().startswith("mailto:"):
            return hitta_epost(href)
    return hitta_epost(_text(el))


def _parti_cell(cell) -> str:
    """Partiet som text, eller från logotypens alt/title (Netpublicator, Lund m.fl.)."""
    t = _text(cell)
    if t:
        return t
    for sel in ("img::attr(alt)", "img::attr(title)", "a::attr(title)"):
        v = (cell.css(sel).get() or "").strip()
        if v:
            return v
    return ""


def _kolumnkarta(headers: list[str]) -> dict[str, int]:
    karta = {}
    for i, h in enumerate(headers):
        for f, rx in RUBRIK.items():
            if f not in karta and rx.search(h):
                karta[f] = i
    return karta


def _rubrik_fore(el) -> str:
    try:
        r = el.xpath("preceding::*[self::h2 or self::h3 or self::h4 or self::h5][1]")
        return _text(r[0]) if r else ""
    except Exception:
        return ""


def _roll_ur_rubrik(rubrik: str) -> str:
    """'Ledamöter' -> 'Ledamot', 'Ersättare' -> 'Ersättare', annars ''."""
    r = (rubrik or "").lower()
    if re.search(r"ersättare|ersattare|suppleant", r):
        return "Ersättare"
    if re.search(r"ledamöter|ledamot|ledamoter", r):
        return "Ledamot"
    return ""


def tolka_tabeller(page, org_slug: str, organ_namn: str, kalla_url: str):
    """Yieldar Observation från alla tabeller på sidan."""
    for tabell in page.css("table"):
        rubrik = _rubrik_fore(tabell)
        rubrik_roll = _roll_ur_rubrik(rubrik)
        rubrik_parti = rubrik if normalisera_parti(rubrik) in PARTIER else ""
        rader = tabell.css("tr")
        if len(rader) < 2:
            continue
        headers = [_text(c) for c in rader[0].css("th,td")]
        karta = _kolumnkarta(headers)
        start = 1 if ("namn" in karta or "efternamn" in karta or any(RUBRIK["roll"].search(h) for h in headers)) else 0
        for tr in rader[start:]:
            celler = tr.css("td")
            if not celler:
                continue
            texter = [_text(c) for c in celler]
            fornamn = efternamn = ""
            if "efternamn" in karta and karta["efternamn"] < len(texter):
                efternamn = texter[karta["efternamn"]]
                fornamn = texter[karta["fornamn"]] if "fornamn" in karta and karta["fornamn"] < len(texter) else ""
                namn = f"{fornamn} {efternamn}".strip()
                parti = _parti_cell(celler[karta["parti"]]) if "parti" in karta and karta["parti"] < len(celler) else ""
                roll = texter[karta["roll"]] if "roll" in karta and karta["roll"] < len(texter) else ""
                organ = texter[karta["organ"]] if "organ" in karta and karta["organ"] < len(texter) else organ_namn
                epost = _epost_i(tr)
            elif "namn" in karta and karta["namn"] < len(texter):
                namn = texter[karta["namn"]]
                parti = _parti_cell(celler[karta["parti"]]) if "parti" in karta and karta["parti"] < len(celler) else ""
                roll = texter[karta["roll"]] if "roll" in karta and karta["roll"] < len(texter) else ""
                organ = texter[karta["organ"]] if "organ" in karta and karta["organ"] < len(texter) else organ_namn
                epost = _epost_i(celler[karta["epost"]]) if "epost" in karta and karta["epost"] < len(texter) else _epost_i(tr)
            else:
                # inga rubriker: gissa INTE, utan kräv att raden har ett partitoken
                # eller ett rolltoken så att vi vet att det är en förtroendevald-rad
                namn, parti, roll, organ, epost = "", "", "", organ_namn, _epost_i(tr)
                for t in texter:
                    if not namn and t and not _PARTI_TOKEN.match(t) and not _ROLL_ORD.search(t) and "@" not in t and len(t) < 80:
                        namn = t
                    elif _PARTI_TOKEN.match(t) and not parti:
                        parti = t
                    elif _ROLL_ORD.search(t) and not roll:
                        roll = t
                if not (parti or roll):
                    continue
            namn, prefixroll = skala_rollprefix(namn)
            roll = roll or prefixroll
            if not namn or len(namn) > 80 or not ar_personnamn(namn):
                continue
            if not roll and rubrik_roll:
                roll = rubrik_roll
            if not parti and rubrik_parti:
                parti = rubrik_parti
            pid = ""
            for href in tr.css("a::attr(href)").getall():
                m = re.search(r"/(?:person|politician)/([0-9a-f-]{20,})", href or "", re.I)
                if m:
                    pid = m.group(1)
                    break
            yield Observation(org_slug=org_slug, organ_namn=organ, namn_raw=namn, fornamn=fornamn,
                              efternamn=efternamn, roll_raw=roll, parti_raw=parti, epost=epost,
                              kalla_url=kalla_url, extern_person_id=pid)


_LISTRAD = re.compile(
    r"^(?P<namn>[^,(]{3,60}?)\s*\((?P<parti>[^()]{1,40}(?:\([^()]{1,5}\))?)\)\s*[,:\-–]?\s*(?P<roll>.*)$")


def tolka_listor(page, org_slug: str, organ_namn: str, kalla_url: str):
    """Tolkar listor av typen 'Anna Berg (S), ordförande' i li/p-element.
    Saknas roll på raden används närmast föregående rubrik ('Ledamöter', 'Ersättare')."""
    rubrik_roll = ""
    for el in page.css("h2, h3, h4, h5, li, p"):
        tag = (getattr(el, "tag", "") or "").lower()
        t = _text(el)
        if tag in ("h2", "h3", "h4", "h5"):
            rubrik_roll = _roll_ur_rubrik(t)
            continue
        m = _LISTRAD.match(t)
        if not m:
            continue
        roll = m.group("roll").strip()
        if roll and normalisera_roll(roll) == "ovrigt" and not _ROLL_ORD.search(roll):
            roll = ""
        parti = m.group("parti").strip()
        namn, prefixroll = skala_rollprefix(m.group("namn").strip())
        roll = roll or prefixroll or rubrik_roll
        if not ar_personnamn(namn):
            continue
        riksparti = normalisera_parti(parti) in PARTIER
        lokalt = bool(re.search(r"parti|lista|alternativ|initiativ|demokrat", parti, re.I))
        if not (riksparti or (lokalt and roll)) or len(namn.split()) < 2:
            continue
        yield Observation(org_slug=org_slug, organ_namn=organ_namn, namn_raw=namn,
                          roll_raw=roll, parti_raw=parti, epost=_epost_i(el), kalla_url=kalla_url)
