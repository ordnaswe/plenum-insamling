"""Inspektera en sajt innan adapter-konfig skrivs.

    python -m plenum.inspect https://haninge.tromanpublik.se/

Skriver ut: statuskod, titel, h1, alla interna URL-mönster (grupperade på
sökväg utan siffror) med antal, samt rubrikraden i varje tabell. Det är
underlaget för organ_url_monster / person_url_monster / organ_lankar.
"""
from __future__ import annotations
import re
import sys
from collections import Counter
from urllib.parse import urljoin, urlparse

from .fetch import Hamtare


def main(url: str):
    with Hamtare() as h:
        r = h.get(url)
        print("status:", r.status, "| url:", r.url)
        print("title:", (r.css("title::text").get() or "").strip())
        print("h1:", [x.strip() for x in r.css("h1::text").getall()])
        host = urlparse(r.url).netloc
        monster = Counter()
        exempel = {}
        for href in r.css("a::attr(href)").getall():
            if not href or href.startswith(("mailto:", "javascript:", "#")):
                continue
            u = urljoin(r.url, href)
            if urlparse(u).netloc != host:
                continue
            p = urlparse(u)
            key = re.sub(r"\d+", "N", p.path) + ("?" + re.sub(r"=\S+?(&|$)", "=N\\1", p.query) if p.query else "")
            monster[key] += 1
            exempel.setdefault(key, u)
        print("\nInterna URL-mönster:")
        for k, n in monster.most_common(40):
            print(f"  {n:4d}  {k}    ex: {exempel[k]}")
        print("\nTabeller:")
        for i, t in enumerate(r.css("table")):
            rader = t.css("tr")
            rub = [c.get_all_text(strip=True) for c in rader[0].css("th,td")] if rader else []
            print(f"  #{i}: {len(rader)} rader, rubrik: {rub}")
        # klassfrekvens: avslöjar kort/div-baserade listor utan tabeller
        from collections import Counter as _C
        kl = _C()
        for el in r.css("[class]"):
            for c in (el.attrib.get("class") or "").split():
                kl[c] += 1
        print("\nVanligaste CSS-klasser:")
        for k, n in kl.most_common(25):
            print(f"  {n:4d}  {k}")
        print("\nSidtext (första 60 rader):")
        for rad in [x.strip() for x in r.get_all_text(separator="\n").splitlines() if x.strip()][:60]:
            print("  ", rad[:120])
        import os
        os.makedirs("data", exist_ok=True)
        with open("data/inspect.html", "w", encoding="utf-8") as f:
            f.write(r.html_content)
        print("\nRå HTML sparad: data/inspect.html")
        print("\nListor (li) med parentes, första 5:")
        n = 0
        for li in r.css("li"):
            t = li.get_all_text(strip=True)
            if "(" in t and len(t) < 120:
                print("  ", t); n += 1
                if n >= 5:
                    break


if __name__ == "__main__":
    main(sys.argv[1])
