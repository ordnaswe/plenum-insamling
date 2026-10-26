"""Inspektera en JavaScript-sajt (t.ex. Stockholms stads eVald) med en riktig webbläsare.

  python -m plenum.inspect_js https://evald.stockholm.se/extern/organ

Öppnar sidan i headless Chromium, väntar tills nätverket är tyst och sparar:
  data/js/renderad.html      sidan som den ser ut efter JavaScript
  data/js/anrop.txt          alla anrop sidan gjorde (metod, status, typ, adress)
  data/js/api_NN.json        svaret från varje anrop som returnerade JSON (högst 30)
Syftet är att hitta det API sidan själv hämtar data från, så att insamlingen kan
läsa samma data direkt i stället för att klicka runt i gränssnittet.
"""
from __future__ import annotations
import json
import os
import sys
from urllib.parse import urlparse

from playwright.sync_api import sync_playwright


def main(url: str, ut: str = "data/js"):
    os.makedirs(ut, exist_ok=True)
    anrop, json_svar = [], []

    def pa_svar(resp):
        try:
            typ = resp.headers.get("content-type", "")
            anrop.append(f"{resp.request.method:6s} {resp.status} {typ[:40]:40s} {resp.url}")
            if "json" in typ and len(json_svar) < 30:
                json_svar.append((resp.url, resp.text()))
        except Exception as e:
            anrop.append(f"(fel vid läsning av svar: {e}) {resp.url}")

    with sync_playwright() as p:
        b = p.chromium.launch(headless=True)
        sida = b.new_page(locale="sv-SE")
        sida.on("response", pa_svar)
        sida.goto(url, wait_until="networkidle", timeout=60000)
        sida.wait_for_timeout(3000)
        html = sida.content()
        # klicka på första länken som ser ut som ett organ, för att se anropen för en organsida
        try:
            lank = sida.locator("a").filter(has_text="fullmäktige").first
            if lank.count():
                lank.click()
                sida.wait_for_load_state("networkidle", timeout=30000)
                sida.wait_for_timeout(2000)
                with open(f"{ut}/renderad_organ.html", "w", encoding="utf-8") as f:
                    f.write(sida.content())
        except Exception as e:
            anrop.append(f"(kunde inte klicka vidare: {e})")
        b.close()

    with open(f"{ut}/renderad.html", "w", encoding="utf-8") as f:
        f.write(html)
    with open(f"{ut}/anrop.txt", "w", encoding="utf-8") as f:
        f.write("\n".join(anrop))
    for i, (u, txt) in enumerate(json_svar):
        with open(f"{ut}/api_{i:02d}.json", "w", encoding="utf-8") as f:
            f.write(json.dumps({"url": u, "svar": txt[:200000]}, ensure_ascii=False))
    egna = [a for a in anrop if urlparse(url).netloc in a]
    print(f"{len(anrop)} anrop, varav {len(egna)} till {urlparse(url).netloc}, {len(json_svar)} JSON-svar")
    print("\n".join(egna[:60]))


if __name__ == "__main__":
    main(sys.argv[1])
