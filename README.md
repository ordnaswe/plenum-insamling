# Plenum scraper

Daglig insamling av alla förtroendevalda (ledamöter, ersättare, presidier) i Sveriges 290 kommuner och 21 regioner, inklusive bolag, nämnder och utskott. GitHub Actions kör, Supabase lagrar.

## Arkitektur

```
config/kallor.csv  ──►  plenum.run  ──►  adapter per källa  ──►  normalize  ──►  Supabase
(311 organisationer)    (shardat 6x)     troman | generic_table | manual     roll/parti/namn   organ, personer, uppdrag,
                                               │                                                korningar, forandringar
                                          plenum.fetch (Scrapling)                              + Storage 'ravdata' (JSONL)
```

**Datamodell (supabase/schema.sql)**

| Tabell | Innehåll | Nyckel |
|---|---|---|
| `organisationer` | kommun/region, system, adapter, base_url | `org_slug` |
| `organ` | nämnd, styrelse, bolag, utskott, revision ... | `(org_slug, organ_norm)` |
| `personer` | förnamn, efternamn, parti, e-post (med källa och datum) | `person_nyckel` = sha1(org, förnamn, efternamn) |
| `uppdrag` | person × organ × roll, med `forst_sedd`, `senast_sedd`, `avslutad` | `uppdrag_nyckel` = sha1(org, organ, namn, roll) |
| `korningar` | en rad per organisation och dag: status, antal, fel, rådatasökväg | |
| `forandringar` | nytt/avslutat uppdrag, ny person, ny e-post: underlag för bevakningsfunktionen | |

Vyer: `v_aktiva_uppdrag` (det sajten läser) och `v_tackning` (vilka kommuner som fungerar, när senast ok).

Historik uppstår automatiskt: ett uppdrag som försvinner ur källan får `avslutad = idag` och `aktiv = false`. Ingen rad raderas. Rådatan 2022-2026 importeras med `mandatperiod = '2022-2026'`.

**Säkring mot dåliga körningar.** Om en körning ser färre än 60 % av organisationens aktiva uppdrag (`PLENUM_SAKRING`) avslutas inget, körningen märks `skippad_sakring`. Det skyddar mot att en halvladdad sida tömmer en kommun.

**Källtransparens.** Varje uppdrag och varje e-post har `kalla_url`. Tomt fält betyder "saknas i källan", aldrig gissning. `namn_osakert` flaggar namn med tre ord där vi inte kan veta var efternamnet börjar.

## Hur blockering hanteras (plenum/fetch.py)

1. `FetcherSession(impersonate="chrome", stealthy_headers=True)`: riktig Chrome-TLS-fingerprint och webbläsarheaders. Kommunsajter och Troman Publik har normalt inget aggressivt botskydd; det här räcker nästan alltid.
2. Artighet: 1,5-3,5 s slumpad paus per domän, robots.txt respekteras. Vi är gäst på små servrar.
3. Vid 403/429/503 eller Cloudflare-sida: backoff, nytt försök, sedan fallback till `StealthyFetcher` (headless Chromium med fingerprint-spoofing, löser Cloudflare Turnstile) när `PLENUM_BROWSER=1`.
4. Om en sajt blockar GitHubs IP-intervall: sätt `PLENUM_PROXY` (secret). Scrapling har inbyggd proxyrotator om det behövs.
5. Blockering loggas som `status = blockerad` i `korningar`; nästa dag försöker vi igen.

## Adaptrar

| Adapter | Används för | Konfig i `extra` (JSON) |
|---|---|---|
| `troman` | `[kund].tromanpublik.se`, standardiserat format | `organ_url_monster`, `person_url_monster`, `max_sidor` |
| `generic_table` | hemmasnickrade sajter med tabeller eller listor "Namn (P), roll" | `organ_lankar` (CSS för länkar till organ), `organ_rubrik` (standard `h1`) |
| `manual` | kommuner utan maskinläsbar data; körningen loggas `ingen_kalla` | |

Lägg till det andra stora systemet som `plenum/adapters/<namn>.py` och registrera i `adapters/__init__.py` när vi vet vilket det är.

**Viktigt om Troman-adaptern.** Jag har inte kunnat läsa en live Troman-instans från miljön koden skrevs i (domänen var inte nåbar). Adaptern är därför en upptäckande crawler inom subdomänen med breda URL-mönster, inte hårdkodade selektorer. Första steget är:

```bash
python -m plenum.inspect https://haninge.tromanpublik.se/
```

Det skriver ut alla interna URL-mönster och tabellrubriker. Lås sedan `organ_url_monster` och `person_url_monster` i `kallor.csv` (samma värde för alla Troman-rader). Kör därefter `--org haninge --dry-run` och läs `data/out/haninge.jsonl`.

## Komma igång

```bash
pip install -r requirements.txt
scrapling install                       # bara om PLENUM_BROWSER=1
cp .env.example .env                    # fyll i Supabase

# 1. Schema
#    Klistra in supabase/schema.sql i Supabase SQL Editor. Skapa bucket 'ravdata' (privat).

# 2. Importera historiken 2022-2026
python -m plenum.import_legacy data/raw/politiker_*.csv --out data/legacy.jsonl
python -m plenum.import_legacy data/raw/politiker_*.csv --supabase

# 3. Testa en källa utan att röra databasen
python -m plenum.run --org haninge --dry-run -v

# 4. Första riktiga körningen
python -m plenum.run --synka-org --org haninge
```

GitHub: lägg `SUPABASE_URL`, `SUPABASE_SERVICE_KEY` (och ev. `PLENUM_PROXY`) som repo-secrets. Workflown `daglig-insamling.yml` kör 6 parallella shards varje natt och personsidor (e-post) på söndagar.

## Status för config/kallor.csv

* 50 Troman-kommuner ifyllda (subdomäner verifierade via Google-index maj 2026). Din `troman_data.py` har fler (ca 130 kommuner + 14-16 regioner): komplettera därifrån.
* Stockholm: `evald.stockholm.se`, generic_table, inaktiv tills `organ_lankar` satts efter inspect.
* Övriga 239 kommuner och alla regioner står som `manual` tills system och URL fyllts i. Fyll kolumnerna `system`, `adapter`, `base_url`, `extra`.

## Verifierat i den här leveransen

* 6 enhetstester (normalisering + tabell/listtolkning) passerar.
* Dry-run mot lokal testsajt: generic_table följer organlänkar, tolkar tabell och lista, plockar mailto.
* Legacy-import av din rådata: 62 271 unika uppdrag, 269 organisationer, 279 rader (0,4 %) med roll `ovrigt` (t.ex. "Representant", "vigselförrättare") där `roll_raw` behålls.
* Inte verifierat: Troman-adapterns URL-mönster mot live-sajt (se ovan).
