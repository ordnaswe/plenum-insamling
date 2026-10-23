"""Normalisering av roll, parti, organtyp och namn.

Vokabulären för roller bygger på de faktiska värdena i Plenums rådata 2022-2026
(33 764 rader, 269 organisationer). Okända värden blir "ovrigt" och roll_raw
behålls alltid, så inget tappas.
"""
from __future__ import annotations
import re
import unicodedata

# ---------- roll ----------
ROLL_MONSTER = [
    # ordning spelar roll: mer specifika först
    (r"ers[äa]ttare\s+(f[öo]r\s+)?ombud", "ersattare_ombud"),
    (r"ers[äa]ttare\s+(f[öo]r\s+)?revisor", "ersattare_revisor"),
    (r"lekmannarevisor", "lekmannarevisor"),
    (r"revisor", "revisor"),
    (r"(f[öo]rste|1:?e|1:a|1\.)\s*(vice|v\.?)\s*ordf", "forste_vice_ordforande"),
    (r"(andre|2:?e|2:a|2\.)\s*(vice|v\.?)\s*ordf", "andre_vice_ordforande"),
    (r"(tredje|3:?e|3\.)\s*(vice|v\.?)\s*ordf", "tredje_vice_ordforande"),
    (r"\bvice\s*ordf|\bv\.?\s*ordf", "vice_ordforande"),
    (r"\bordf", "ordforande"),
    (r"gruppledare", "gruppledare"),
    (r"kommunalr[åa]d|regionr[åa]d|oppositionsr[åa]d|borgarr[åa]d", "rad"),
    (r"insynsplats|insyn", "insynsplats"),
    (r"ombud", "ombud"),
    (r"n[äa]mndeman", "namndeman"),
    (r"ers[äa]ttare|suppleant", "ersattare"),
    (r"ledamot|ledamöter|ordinarie", "ledamot"),
]
_ROLL_RE = [(re.compile(p, re.I), v) for p, v in ROLL_MONSTER]

ROLL_RANG = {  # för sortering i gränssnitt
    "ordforande": 1, "forste_vice_ordforande": 2, "andre_vice_ordforande": 3,
    "tredje_vice_ordforande": 4, "vice_ordforande": 5, "rad": 6, "gruppledare": 7,
    "ledamot": 10, "ersattare": 20, "revisor": 30, "lekmannarevisor": 31,
    "ersattare_revisor": 32, "ombud": 40, "ersattare_ombud": 41,
    "insynsplats": 50, "namndeman": 60, "ovrigt": 99,
}


def normalisera_roll(roll_raw: str) -> str:
    s = (roll_raw or "").strip()
    for rx, val in _ROLL_RE:
        if rx.search(s):
            return val
    return "ovrigt"


# ---------- parti ----------
PARTIER = {
    "S": ["s", "socialdemokraterna", "arbetarepartiet-socialdemokraterna", "arbetarepartiet socialdemokraterna", "sap"],
    "M": ["m", "moderaterna", "moderata samlingspartiet"],
    "SD": ["sd", "sverigedemokraterna"],
    "C": ["c", "centerpartiet", "centern"],
    "V": ["v", "vänsterpartiet", "vansterpartiet"],
    "KD": ["kd", "kristdemokraterna"],
    "L": ["l", "fp", "liberalerna", "folkpartiet", "folkpartiet liberalerna"],
    "MP": ["mp", "miljöpartiet", "miljopartiet", "miljöpartiet de gröna", "miljopartiet de grona"],
}
_PARTI_LOOKUP = {alias: kod for kod, aliases in PARTIER.items() for alias in aliases}


def normalisera_parti(parti_raw: str) -> str:
    """Riksdagspartier -> förkortning. Lokala partier behålls med sitt namn.
    Tomt/okänt -> ''. Vi gissar aldrig."""
    s = (parti_raw or "").strip().strip("()").strip()
    if not s or s in {"-", "–", "—", "Partilös", "partilös", "Politisk vilde", "Opolitisk"}:
        return "" if not s or s in {"-", "–", "—"} else s
    key = s.lower().replace("(", "").replace(")", "").strip()
    if key in _PARTI_LOOKUP:
        return _PARTI_LOOKUP[key]
    return s  # lokalt parti, t.ex. "Sjukvårdspartiet i Värmland"


# ---------- organ ----------
ORGAN_MONSTER = [
    (r"fullm[äa]ktige", "fullmaktige"),
    (r"utskott|arbetsutskott|\bau\b|beredning", "utskott"),
    (r"kommunstyrelse|regionstyrelse|stadsstyrelse|\bks\b", "styrelse"),
    (r"\bab\b|aktiebolag|\bbolag|holding|fastighets|energi|bostäder|bostader|hamn|stadshus|koncern", "bolag"),
    (r"revision|revisor", "revision"),
    (r"valberedning", "valberedning"),
    (r"f[öo]rbund|samordningsf", "forbund"),
    (r"stiftelse", "stiftelse"),
    (r"n[äa]mnd|styrelsen f[öo]r|\bnämnden\b", "namnd"),
    (r"r[åa]d\b|rådet", "rad"),
]
_ORGAN_RE = [(re.compile(p, re.I), v) for p, v in ORGAN_MONSTER]


def normalisera_organ_typ(organ_namn: str) -> str:
    s = organ_namn or ""
    for rx, val in _ORGAN_RE:
        if rx.search(s):
            return val
    return "ovrigt"


def organ_norm(organ_namn: str) -> str:
    """Nyckelvänlig form av organnamn (gemener, utan dubbla mellanslag)."""
    s = unicodedata.normalize("NFKC", organ_namn or "").lower()
    s = re.sub(r"\s+", " ", s).strip()
    return s


# ---------- namn ----------
_PREFIX_PAREN = re.compile(r"^\(([^)]{1,6})\)\s*")      # "(Ox) Dag Bergentoft"
_TRAILING_PARTI = re.compile(r"\s*\(([^()]{1,40})\)\s*$")  # "Anna Berg (S)"
_SMALL = {"von", "af", "de", "van", "der", "da", "la", "le", "di", "del", "du", "el"}


def _titlecase(token: str) -> str:
    if token.lower() in _SMALL:
        return token.lower()
    return "-".join(p[:1].upper() + p[1:].lower() for p in token.split("-"))


def dela_namn(namn_raw: str) -> tuple[str, str, bool, str]:
    """Returnerar (fornamn, efternamn, osakert, parti_i_namn).

    Regel: sista ordet = efternamn, resten = förnamn, utom när ett
    partikelord (von, af, de ...) föregår det. Flerordsefternamn utan
    partikel kan inte avgöras från en textsträng, därför flaggas osakert.
    Namn i VERSALER görs om till Titelform.
    """
    s = (namn_raw or "").strip()
    s = _PREFIX_PAREN.sub("", s)
    parti_i_namn = ""
    m = _TRAILING_PARTI.search(s)
    if m:
        parti_i_namn = m.group(1).strip()
        s = s[: m.start()].strip()
    s = re.sub(r"\s+", " ", s)
    if not s or s in {"-", "–", "—"}:
        return "", "", True, parti_i_namn
    if s == s.upper() and len(s) > 3:  # ADAM PALM -> Adam Palm
        s = " ".join(_titlecase(t) for t in s.split(" "))
    delar = s.split(" ")
    if len(delar) == 1:
        return "", delar[0], True, parti_i_namn
    # partikel: "Carl von Essen" -> förnamn Carl, efternamn von Essen
    for i in range(1, len(delar) - 1):
        if delar[i].lower() in _SMALL:
            return " ".join(delar[:i]), " ".join(delar[i:]), False, parti_i_namn
    osakert = len(delar) > 2  # kan vara dubbelt förnamn eller dubbelt efternamn
    return " ".join(delar[:-1]), delar[-1], osakert, parti_i_namn


_EPOST = re.compile(r"[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}")


def hitta_epost(text: str) -> str:
    if not text:
        return ""
    t = text.replace("mailto:", "").replace("[at]", "@").replace("(at)", "@")
    m = _EPOST.search(t)
    return m.group(0).lower() if m else ""


def berika(obs) -> None:
    """Fyller normaliserade fält på en Observation in-place."""
    if obs.efternamn:   # källan har separata kolumner: lita på dem
        obs.namn_osakert = False
    else:
        fn, en, osak, parti_i_namn = dela_namn(obs.namn_raw)
        obs.fornamn, obs.efternamn, obs.namn_osakert = fn, en, osak
        if not obs.parti_raw and parti_i_namn:
            obs.parti_raw = parti_i_namn
    obs.parti = normalisera_parti(obs.parti_raw)
    obs.roll = normalisera_roll(obs.roll_raw)
    obs.organ_typ = normalisera_organ_typ(obs.organ_namn)
    obs.organ_norm = organ_norm(obs.organ_namn)
    if obs.epost:
        obs.epost = hitta_epost(obs.epost)
