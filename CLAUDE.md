# CLAUDE.md — TDCat Energy Dashboard

Handover notes for any Claude session (local or cloud) working on this repo.

## Ground rules (from the owner)

- **This folder is the LIVE app.** It's an SMB share from OTTO (Mac mini M2), where it runs as `/Users/tdcat/SCRIPTS/ENERGY`. Editors mount it at `/Volumes/SCRIPTS/ENERGY`.
- **Never test against live data.** Copy `grid_data.db`, `config.json` or `static/forecast.json` into a scratch directory and point code at the copy. Open the live DB read-only if you must look (`sqlite3 "file:grid_data.db?mode=ro"`).
- **Commit and push after every change.** Remote: `git@github.com:TDCatUK/tdcat-energy.git`, branch `main`. No pulling is needed because every machine uses the same folder. Never force-push or rewrite history without asking.
- **Add a dated entry to the "Changes" section of `README.md` for every change**, and keep this file current.
- Edits to `app.py` and `harvester.py` take effect on OTTO: the harvester picks them up on its next 5-minute run, but Flask needs a restart. The restart happens on OTTO, so tell the owner when one is needed.

## What it is

A Flask dashboard for the GB grid and a home Tesla Powerwall, public at `energy.tdcat.com` through a Cloudflare tunnel (Cloudflare restricts access by email and IP).

```
cron/launchd on OTTO (every 5 min)
        │
        ▼
 harvester.py ──► Elexon, NESO, PV_Live, Carbon Intensity, Octopus, Open-Meteo,
        │         Powerwall (local LAN via pypowerwall), Cloudflare GraphQL
        ├──► INSERT one row into grid_data.db : energy_snapshots
        └──► overwrite static/forecast.json (raw Open-Meteo payload)

 app.py (Flask :5000)
   /             templates/index.html  + static/script.js  (polls every 2 min)
   /admin        templates/admin.html  (edits config.json via POST /api/config)
   /about        templates/about.html  (explains the metrics)
   /api/data     latest row + last 288 rows (≈24 h) + today's Powerwall kWh totals
   /api/config   GET merges config.json over DEFAULT_CONFIG; POST overwrites config.json
```

## Files

| Path | Role | Tracked? |
|---|---|---|
| `app.py` | Flask server, `/api/data` aggregation (mix %, kWh integration) | yes |
| `harvester.py` | Data collector, one DB row per run | yes |
| `static/script.js` | All rendering: doughnut, stacked history, flow SVG, map, demand breakdown, sparklines | yes |
| `static/style.css`, `logo.png`, `favicon.png`, `map.webp`, `robots.txt`, `sitemap.xml`, `google*.html` | Static assets / SEO | yes |
| `templates/*.html` | Tailwind (CDN) pages | yes |
| `config.json` | Colours, thresholds, map node positions, footer links. Rewritten live by `/admin`; tracked as a settings backup | yes |
| `requirements.txt` | Flask, pypowerwall, python-dotenv, requests, teslapy, urllib3 | yes |
| `.env` | API keys, MPAN/MPRN, meter serials, tariff codes, endpoint URLs | **no (secret)** |
| `.powerwall` | pypowerwall auth cookie cache | **no (secret)** |
| `grid_data.db` | SQLite, ~48k rows since 2026-04-23, ~45 MB | **no (live data)** |
| `harvester.log`, `static/forecast.json`, `*.BACKUP`, `grid_data_backup_*.db` | Live output / old backups | **no** |
| `archive/` | Old one-off and test scripts (DB patchers, early harvester versions, API probes, `setup_db.py` schema seed). Not used by the app. **Never run the fix/patch scripts against the live DB.** | yes |
| `archive/test_pw.py`, `archive/visitors.py` | Test scripts with hard-coded credentials | **no (secret)** |

## Database: `energy_snapshots`

Primary key `timestamp` (ISO UTC string `YYYY-MM-DDTHH:MM:SSZ`). Columns were added over time with `ALTER TABLE`.

- Grid: `carbon_intensity` (gCO2/kWh), `demand_mw`, `total_generation_mw`, `net_flow_mw` (interconnector net, +import), `wholesale_price` (System Sell Price £/MWh), `day_ahead_price`, `market_index_price` (£/MWh), `grid_frequency` (Hz), `net_imbalance_volume` (MWh), `embedded_wind_mw`
- JSON text: `generation_mix` `{label: MW}` (Elexon FUELINST labels plus "Solar" and "LV Wind"), `interconnector_flows` `[{name, flow}]`
- Powerwall: `pw_solar_w`, `pw_home_w`, `pw_battery_w` (+ discharge), `pw_grid_w` (+ import), `pw_level` (%), `pw_grid_status`
- Weather: `temp_c`, `wind_mph`, `daylight_secs`, `cloud_cover`
- Octopus: `oct_import_pence`, `oct_export_pence` (p/kWh inc VAT), `oct_yest_import`, `oct_yest_export` (kWh), `oct_yest_gas` (m³), `oct_yest_date`
- Cloudflare: `cf_visits_24h`, `cf_requests_24h`, `cf_bytes_24h`

**Important:** `demand_mw` is stored as **ITSDO + PV_Live solar + embedded wind**, not raw ITSDO.

## Data sources (endpoints in `.env`)

Elexon BMRS: FUELINST (mix + interconnectors), ITSDO (demand), system-prices (SSP + NIV), market-index (APXMIDP / N2EXMIDP), frequency stream. NESO datastore resource `db6c038f-…` (embedded wind forecast). PV_Live `gsp/0` (national solar). Carbon Intensity `/intensity`. Octopus v1 (Agile import/export unit rates, consumption). Open-Meteo forecast (mph, Europe/London).

## Known issues (audit 2026-10-06)

See README "Changes" for what has since been fixed.

1. ~~Octopus API key rejected (401) from 2026-09-30 16:55 UTC.~~ **Resolved 2026-10-06:** the owner regenerated the key in `.env`; the first good row was 12:00 UTC. Octopus fields are 0 for the gap.
2. **Embedded generation double-counted in the demand breakdown.** `demand_mw` already includes solar and LV wind, but `script.js` treats it as pure ITSDO ("Transmission") and adds embedded again for Net and Gross. "National" is inflated by embedded too.
3. **"Day-ahead price" is N2EX MIDP**, which is usually 0 (no volume). It isn't a day-ahead price.
4. **Mix percentages:** in `app.py` the denominator includes negative pumped storage (pumping) and the fuel gets a negative %. The history chart and fuel-detail chart then rebuild GW from % using different totals (total supply vs `demand_mw`).
5. **Powerwall "today" kWh** uses the UTC date, not the UK local day (off by an hour during BST). Gaps over 1 h are counted as 5 minutes.
6. **Octopus "yesterday"** sums the latest 48 half-hours returned, which can span two days, and labels them with the latest slot's date.
7. **Unmapped interconnector** `INTGRNL` (Greenlink, Ireland) shows as a raw code and is left out of the Ireland map flow and capacity list. Interconnector capacities are hard-coded in `script.js`.
8. **Carbon intensity** uses `actual`, which is often null for the current half-hour; it falls back to 0, then the front end forward-fills.
9. `station_load_mw` is hard-coded to 500 MW.
10. `/api/config` POST and `/admin` have no app-level auth; they rely on Cloudflare.
11. `datetime.utcnow()` deprecation warnings flood `harvester.log` (~7 MB).

## Testing locally (safe)

```bash
SCR=<scratch dir>
cp grid_data.db config.json "$SCR"/ && mkdir -p "$SCR/static" && cp static/forecast.json "$SCR/static/"
# then run code with cwd=$SCR (app.py/harvester.py use relative paths), e.g. via PYTHONPATH
```

`app.py` and `harvester.py` use **relative paths** (`grid_data.db`, `config.json`, `static/forecast.json`), so the working directory decides which files they touch. Don't run `harvester.py` from the live folder when testing: it INSERTs into the live DB.
