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
| `harvester.log`, `static/forecast.json` | Live output. `harvester.log` is appended to by the scheduler on OTTO. `trim_log()` in `harvester.py` keeps the last 90 days (`LOG_KEEP_DAYS`), rewriting the file in place, only when stdout is that file. If clearing it by hand, empty it in place (`: > harvester.log`) right after a run; never delete or replace it. | **no** |

Old one-off scripts (DB patchers, early harvester versions, API probes, the `setup_db.py` schema seed) and the April DB backups were removed on 2026-10-06. The committed scripts can still be recovered from git: `git show 6086212:archive/<name>.py`.

## Database: `energy_snapshots`

Primary key `timestamp` (ISO UTC string `YYYY-MM-DDTHH:MM:SSZ`). Columns were added over time with `ALTER TABLE`.

- Grid: `carbon_intensity` (gCO2/kWh), `demand_mw`, `total_generation_mw`, `net_flow_mw` (interconnector net, +import), `wholesale_price` (System Sell Price £/MWh), `day_ahead_price`, `market_index_price` (£/MWh), `grid_frequency` (Hz), `net_imbalance_volume` (MWh), `embedded_wind_mw`
- JSON text: `generation_mix` `{label: MW}` (Elexon FUELINST labels plus "Solar" and "LV Wind"), `interconnector_flows` `[{name, flow}]`
- Powerwall: `pw_solar_w`, `pw_home_w`, `pw_battery_w` (+ discharge), `pw_grid_w` (+ import), `pw_level` (%), `pw_grid_status`
- Weather: `temp_c`, `wind_mph`, `daylight_secs`, `cloud_cover`
- Octopus: `oct_import_pence`, `oct_export_pence` (p/kWh inc VAT), `oct_yest_import`, `oct_yest_export` (kWh), `oct_yest_gas` (m³), `oct_yest_date`
- Cloudflare: `cf_visits_24h`, `cf_requests_24h`, `cf_bytes_24h`

**Stored-value quirks (don't change these without migrating history):**
- `demand_mw` is stored as **ITSDO + PV_Live solar + embedded wind**, not raw ITSDO. `app.py` takes the `Solar` and `LV Wind` mix values back off to get ITSDO (this matches Elexon's ITSDO to within rounding).
- `total_generation_mw` includes pumped storage as a negative number while pumping. `app.py` ignores this column and recomputes generation from the mix, with pumping clamped out.
- `day_ahead_price` is N2EX MIDP when it has traded volume (it hasn't for months), else 0. It isn't shown anywhere.
- `pw_level` is the gateway's **raw** state of charge (in the DB and the API). `script.js` shows the Tesla-app figure, `appBatteryLevel()` = (raw − 5) / 0.95, clamped to 0–100.
- `oct_yest_*` are totals for the most recent UK day that's **complete on all three meters** (export and gas lag import by about a day), and `oct_yest_date` is that day.

**Demand identity (checked against Elexon 2026-10-06):** ITSDO = INDO + exports + pumped-storage pumping + 500 MW station load. Net = INDO + embedded. Gross = ITSDO + embedded.

## Data sources (endpoints in `.env`)

Elexon BMRS: FUELINST (mix + interconnectors), ITSDO (demand), system-prices (SSP + NIV), market-index (APXMIDP / N2EXMIDP), frequency stream. NESO datastore resource `db6c038f-…` (embedded wind forecast). PV_Live `gsp/0` (national solar). Carbon Intensity `/intensity`. Octopus v1 (Agile import/export unit rates, consumption). Open-Meteo forecast (mph, Europe/London).

## API contract between `app.py` and `script.js`

Each `/api/data` history row carries `transmission_mw` (ITSDO), `embedded_mw` (solar + LV wind), `supply_mw` (generation + gross imports) and `mix: [{fuel, mw, perc}]`, where `perc` is the share of `supply_mw`. `script.js` reads these directly. **Deploy order matters:** Flask on OTTO only picks up `app.py` changes after a restart, while static files go live at once. So when the API shape changes, restart Flask before deploying `script.js` that depends on the new fields.

## Known issues

Audit 2026-10-06. Items 1–8 were fixed the same day (see README Changes).

1. ~~Octopus API key rejected (401) from 2026-09-30 16:55 UTC.~~ Owner regenerated the key. Octopus fields are 0 for the gap.
2. ~~Embedded generation double-counted in the demand breakdown.~~
3. ~~MIDP fell to £0 after UTC midnight / zero-volume prices.~~ The "day-ahead" column remains effectively unused.
4. ~~Mix percentages included negative pumped storage; charts rebuilt GW from % with mismatched totals.~~
5. ~~Powerwall "today" kWh used the UTC day.~~ Gaps over 1 h still count as 5 minutes (deliberately unchanged).
6. ~~Octopus "yesterday" summed the latest 48 half-hours.~~ Octopus sometimes zero-fills missing half-hours (e.g. import on 04 Oct 2026 = 0.03 kWh), which can't be fixed this side.
7. ~~Greenlink (`INTGRNL`) unmapped.~~ Interconnector capacities are still hard-coded in `script.js`.
8. ~~Carbon intensity fell to 0 when `actual` was null~~; it now falls back to `forecast`.
9. `station_load_mw` is hard-coded to 500 MW (Elexon uses the same constant, so this is right).
10. `/api/config` POST and `/admin` have no app-level auth; they rely on Cloudflare.
11. ~~`datetime.utcnow()` deprecation warnings flooded `harvester.log`.~~ Fixed 2026-10-06; the old log was cleared. The log now keeps 90 days (about 30 KB/day).
12. The stacked generation (generation + gross imports) sits about one export's worth above the dashed demand line (ITSDO + embedded), so `about.html`'s "over-producing" explanation is a simplification.

## Testing locally (safe)

```bash
SCR=<scratch dir>
cp grid_data.db config.json "$SCR"/ && mkdir -p "$SCR/static" && cp static/forecast.json "$SCR/static/"
# then run code with cwd=$SCR (app.py/harvester.py use relative paths), e.g. via PYTHONPATH
```

`app.py` and `harvester.py` use **relative paths** (`grid_data.db`, `config.json`, `static/forecast.json`), so the working directory decides which files they touch. Don't run `harvester.py` from the live folder when testing: it INSERTs into the live DB.
