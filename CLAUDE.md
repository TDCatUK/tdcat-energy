# CLAUDE.md — TDCat Energy Dashboard

Handover notes for any Claude session (local or cloud) working on this repo.

## Ground rules (from the owner)

- **This folder is the LIVE app.** It's an SMB share from OTTO (Mac mini M2), where it runs as `/Users/tdcat/SCRIPTS/ENERGY`. Editors mount it at `/Volumes/SCRIPTS/ENERGY`.
- **Never test against live data.** Copy `grid_data.db`, `config.json` or `static/forecast.json` into a scratch directory and point code at the copy. Open the live DB read-only if you must look (`sqlite3 "file:grid_data.db?mode=ro"`).
- **Commit and push after every change.** Remote: `git@github.com:TDCatUK/tdcat-energy.git`, branch `main`. No pulling is needed because every machine uses the same folder. Never force-push or rewrite history without asking.
- **Add a dated entry to the "Changes" section of `README.md` for every change**, and keep this file current.
- **User-visible changes also go on the public Changelog page** (`templates/changelog.html`): one compact card per date with "New" and "Fixed" columns, written in the first person by the owner ("I've added…"), short plain-English bullets. Leave out security details, internal/behind-the-scenes work and admin-only settings.
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
   /about        templates/about.html  (explains the metrics; keep it in step with any maths changes)
   /changelog    templates/changelog.html  (public, plain-English list of changes)
   /status       templates/status.html  (data-source health; reads /api/status)
   /api/demand/recent      last 31 days of NESO half-hourly ND + rooftop solar, stamped with UK local start time
   /api/demand/duck?month= average ND/solar by half-hour for that month, every year since 2010, plus solar records
   /history      templates/history.html + static/history.js (7 days hourly, 30 days / 1 year daily)
   /api/history?range=   averages per hour or UK day plus a summary for the range
   /api/status   each source's state, last good fetch, error, 7-day hourly record (?summary=1 for the menu dot)
   /api/forecast           Agile import/export rates and the national carbon forecast from the current half-hour on
   /api/frequency?hours=   every 15-second frequency reading for the last 0.25–24 h, plus today's low/high/time outside limits
   /api/data     latest row + last 288 rows (≈24 h) + today's Powerwall kWh totals
   /api/config   GET only (public): config.json merged over DEFAULT_CONFIG
   /admin/api/config  POST: validates and atomically replaces config.json (protected by Cloudflare Access on /admin/*)
```

## Files

| Path | Role | Tracked? |
|---|---|---|
| `app.py` | Flask server, `/api/data` aggregation (mix %, kWh integration) | yes |
| `harvester.py` | Data collector, one DB row per run | yes |
| `static/script.js` | All rendering: doughnut, stacked history, flow SVG, map, demand breakdown, sparklines | yes |
| `static/history.js` | The History page's charts and summary (reads `/api/history` and `/api/config`) | yes |
| `static/style.css`, `logo.png`, `favicon.png`, `map.webp`, `robots.txt`, `sitemap.xml`, `google*.html` | Static assets / SEO | yes |
| `templates/*.html` | Tailwind (CDN) pages | yes |
| `config.json` | Colours, thresholds, map node positions, footer links. Rewritten live by `/admin`; tracked as a settings backup | yes |
| `requirements.txt` | Flask, pypowerwall, python-dotenv, requests, teslapy, urllib3 | yes |
| `.env` | API keys, MPAN/MPRN, meter serials, tariff codes, endpoint URLs | **no (secret)** |
| `.powerwall` | pypowerwall auth cookie cache | **no (secret)** |
| `battery_units.json` | Cached list of battery BM unit IDs, refreshed daily by the harvester | **no (live state)** |
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
- Grid batteries (unofficial estimate): `bess_discharge_mw`, `bess_charge_mw`, both positive. Collected live from 2026-10-06 14:20 UTC and backfilled from 2026-10-05 14:35 UTC; NULL before that. To backfill more, fetch PN/BOALF in chunks with `fetch_battery_segments()` and compute each row with `battery_flow_at()`, the same function the live run uses. Run it against a backup first.

**Stored-value quirks (don't change these without migrating history):**
- `demand_mw` is stored as **ITSDO + PV_Live solar + embedded wind**, not raw ITSDO. `app.py` takes the `Solar` and `LV Wind` mix values back off to get ITSDO (this matches Elexon's ITSDO to within rounding).
- `total_generation_mw` includes pumped storage as a negative number while pumping. `app.py` ignores this column and recomputes generation from the mix, with pumping clamped out.
- `day_ahead_price` is N2EX MIDP when it has traded volume (it hasn't for months), else 0. It isn't shown anywhere.
- `pw_level` is the gateway's **raw** state of charge (in the DB and the API). `script.js` shows the Tesla-app figure, `appBatteryLevel()` = (raw − 5) / 0.95, clamped to 0–100.
- `oct_yest_*` are totals for the most recent UK day that's **complete on all three meters** (export and gas lag import by about a day), and `oct_yest_date` is that day.

**Demand identity (checked against Elexon 2026-10-06):** ITSDO = INDO + exports + pumped-storage pumping + 500 MW station load. Net = INDO + embedded. Gross = ITSDO + embedded.

## Grid battery estimate (unofficial)

Elexon has no battery fuel type, so `load_battery_units()` picks batteries out of `/reference/bmunits/all` by National Grid ID convention (5th character `B`, e.g. `BLWNB-1`) or a name matching battery/BESS/energy storage, excluding conventional fuel types (about 146 units, 7.3 GW). Each run, `fetch_battery_flow()` takes each unit's Physical Notification level now (`/datasets/PN/stream`, filtered by `bmUnit`), overridden by the latest Bid-Offer Acceptance in force (`/datasets/BOALF/stream`, 90 min lookback). Batteries outside the BM aren't visible. Elexon FUELINST `OTHER` never goes negative, so batteries aren't in it and aren't double-counted.

## National Gas (GB gas transmission)

`fetch_gas()` in the harvester reads `https://data.nationalgas.com/api/latest-gas-flows` (2-min data, published every 12 min, times in UK local time) and daily stock levels from `/api/find-gas-data-download` (`PUBOBJ330`/`333` storage stock and space left, `PUBOBJ336`/`339` LNG; kWh, latest complete gas day). It writes one row per run to the `gas_snapshots` table (same `timestamp` as `energy_snapshots`), which the harvester creates itself with `CREATE TABLE IF NOT EXISTS`. Daily stock levels (all storage, LNG, and Rough via `PUBOBJ2364`/`2428`) are upserted into `gas_storage_daily` (keyed by `gas_day`). If that table has fewer than 365 rows, the harvester back-fills it from 2020-05-25, the earliest data available, in yearly requests (about 12 s, once). The source has glitches (zero days, and days with stock or capacity far off), so `storage_rows()` in `app.py` skips days more than 1.5 TWh (stock) or 10% (capacity) from their 7-day median. The raw data stays in the DB. `/api/gas/storage` serves the cleaned daily series. `get_gas_storage()` compares the latest day with the same date in up to five previous years; the colour thresholds are in config `gas.storage_thresh_low/high` (% of that average). Supply groups: LNG = Grain + Milford Haven terminals, Storage = storage entry points (incl. Rough), Continent = Bacton IPs, Norway (Langeled) = Easington Langeled entry, North Sea = the remainder of total supply. Rates are mcm/d, linepack mcm. `app.py` `get_gas()` returns `None` until the table exists. The gas-for-power % uses a fixed 39.5 MJ/m³. The full data-item catalogue is at `/api/find-gas-data-folders` (PUBOBJ IDs in each item's description). There's no gas price (SAP) in it.

## NESO half-hourly demand (When Demand Shifts, Duck Curve)

The harvester's `fetch_neso_demand()` runs on a timer, not every run (tracked in the `fetch_log` table; failures are logged too so they retry after the interval):
- every 3 h: NESO "Demand Data Update" (resource `177f6fa4-…`, about 5 weeks of actuals, refreshed each morning, so it runs up to yesterday or this morning) goes into `neso_demand_hh` (date, settlement period, ND, TSD, embedded solar, embedded wind).
- every 24 h: NESO "Historic Demand Data YYYY" (one resource per year) is summarised by month and half-hour into `duck_profiles`, with per-year solar records (max solar share of ND + solar, and half-hours where solar > ND) in `duck_records`. Missing years since 2010 are back-filled; the current year is refreshed daily, adding `neso_demand_hh` rows for every day after the yearly file ends (the file lags a few weeks), so records are at most a day late and nothing is double-counted.
Gotchas: NESO's `datastore_search` breaks when given `fields`, so use `datastore_search_sql` (no SQL functions allowed). Settlement dates come in three formats (`2026-10-05`, `01-OCT-2020`, `01-Oct-23`); `parse_settlement_date()` handles them (don't split on "T": it's in "OCT"). Settlement periods are UK local half-hours from midnight (46 or 50 on clock-change days), so `/api/demand/recent` converts them via UTC. Don't use the dashboard's own `demand_mw` history for timing-sensitive charts: it's the latest *published* ITSDO, so 0–35 min late.

## Grid frequency (15-second readings)

`fetch_frequency()` asks Elexon's frequency stream for everything since the last stored reading (at least the last 12 minutes, at most 7 days), so one request per run brings in every 15-second reading (about 20 per run). They go into `frequency_readings` (`t` = unix seconds UTC, `hz`; `WITHOUT ROWID`, about 21 bytes a reading, ~44 MB a year). While anything before `FREQ_HISTORY_START` (2026-04-23) is missing, each run also back-fills one 7-day chunk (~40k readings, 0.2 s). The newest reading is still stored as `grid_frequency` on the snapshot row. `/api/frequency?hours=` (0.25–24) returns `[t, hz]` pairs plus today's (UK day) min/max with times, seconds outside the admin limits (`frequency.thresh_low/high`) and outside the 49.5–50.5 Hz statutory limits, counting each reading as 15 s. The front end draws it on a linear x axis with Chart.js min-max decimation.

## Agile prices and carbon forecast

`fetch_forecasts()` runs every 30 minutes (`fetch_log` name `forecasts`; `fetch_due(..., 0.4)` so it isn't skipped by a few seconds). It fetches the public Octopus unit rates for `OCT_IMPORT_TARIFF` and `OCT_EXPORT_TARIFF` from the current half-hour on (tomorrow's Agile rates, to 23:00 UK, appear about 16:00) and the national Carbon Intensity `/intensity/{from}/fw48h` forecast. They're upserted into `agile_rates` (`valid_from` PK, `import_p`, `export_p` in p/kWh inc VAT; a missing side never overwrites a stored rate) and `carbon_forecast` (`period_from` PK, `forecast`, `actual`, `index_label`). Both keep history. `/api/forecast` returns everything from the current half-hour on; `script.js` picks the cheapest/most expensive/greenest 6-slot runs itself (`bestWindow`). Carbon colours use the same <100 / <200 g thresholds as the Carbon card.

## Data-source health (the Status page)

Every fetch in the harvester calls `report(source, ok, error, data_time)`; `save_health()` writes the results with the snapshot row (in the offline path too). `source_status` keeps one row per source: `last_ok`, `last_attempt`, `last_error` (+ `last_error_at`), `data_time` (how recent the source's own data is: ISO UTC, a date, or for gas a UK clock time) and `fails` (consecutive failures, reset on success). `source_runs` logs each run's `ok` and `failed` keys (comma lists) and its duration in `seconds`, trimmed to 90 days. Error text comes from `short_error()` and is public, so it must never include URLs or response bodies (Octopus consumption URLs contain the MPAN and meter serial). `SOURCES` in `app.py` lists the keys, names, groups and fetch intervals; a new source needs a `report()` call in the harvester and an entry there. States: `ok`; `warn` after one failure or 3 intervals without success; `fail` after 3 failures in a row or 12 intervals without success. Overall is `fail` if the harvester hasn't run for 15 minutes. Timed sources (NESO, forecasts) only appear in runs where they were due. Keys: internet, fuelinst, itsdo, frequency, system_prices, market_index, batteries, pvlive, lv_wind, carbon, carbon_forecast, neso_demand, neso_history, gas, gas_storage, powerwall, octopus_rates, agile_forecast, octopus_meters, weather, cloudflare.

## History page

`/api/history?range=7d|30d|1y` serves hourly buckets (7d) or UK-day buckets (30d, 1y; days are built from UTC hours, which works because UK offsets are whole hours). `refresh_history()` folds every `energy_snapshots` row into `history_hours` (in memory, keyed by UTC hour start) with `fold_row()`, which runs `summarise_row()` so the maths matches the live charts. After a Flask restart the first request rebuilds everything (~1 s for 48k rows); later requests only refold from the newest hour. `refresh_frequency()` does the same from `frequency_readings` via SQL `GROUP BY t / 3600`, and rebuilds if the limits change or older readings appear (the harvester back-fills backwards). Stored zeros from failed fetches are skipped (carbon 0, MIDP 0, Octopus import and export both 0, Powerwall all 0), and rows over `MAX_PLAUSIBLE_GEN_MW` (65 GW) are ignored. Powerwall kWh per bucket = sum over its hours of each hour's average power × 1 h. A lock guards the shared caches (Flask's server is threaded).

## Data sources (endpoints in `.env`)

Elexon BMRS: FUELINST (mix + interconnectors), ITSDO (demand), system-prices (SSP + NIV), market-index (APXMIDP / N2EXMIDP), frequency stream. NESO datastore resource `db6c038f-…` (embedded wind forecast). PV_Live `gsp/0` (national solar). Carbon Intensity `/intensity`. Octopus v1 (Agile import/export unit rates, consumption). Open-Meteo forecast (mph, Europe/London).

## API contract between `app.py` and `script.js`

Each `/api/data` history row carries `transmission_mw` (ITSDO), `embedded_mw` (solar + LV wind), `supply_mw` (generation + gross imports) and `mix: [{fuel, mw, perc}]`, where `perc` is the share of `supply_mw`. The 24 h generation chart computes its own % from `mw`, so it stays right when the battery band (`bess_discharge_mw`) is toggled on. New page features check that their elements and API fields exist before rendering, because Flask caches templates until it's restarted. `script.js` reads these directly. **Deploy order matters:** Flask on OTTO only picks up `app.py` changes after a restart, while static files go live at once. So when the API shape changes, restart Flask before deploying `script.js` that depends on the new fields.

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
10. ~~Public `POST /api/config` let anyone overwrite `config.json`.~~ Fixed 2026-10-06: saving moved to `/admin/api/config`. Cloudflare Access covers `/admin/*`, so unauthenticated requests are redirected to login before reaching Flask (checked with GET and POST). Anything new that changes data must also live under `/admin/`.
11. ~~`datetime.utcnow()` deprecation warnings flooded `harvester.log`.~~ Fixed 2026-10-06; the old log was cleared. The log now keeps 90 days (about 30 KB/day).
12. The stacked supply (generation + gross imports) sits a median 0.8 GW (2.4%) above the dashed demand line (ITSDO + embedded), ranging from −1.3 to +3.8 GW over a day. This comes from timing (5-min FUELINST vs half-hourly ITSDO) and modelled embedded generation; `about.html` explains it.
13. FUELINST `Other` had a one-off 10.2 GW value in the last 30 days (normally ~0.5–1 GW): probably a bad Elexon row, not yet investigated. Two rows add up to 334–377 GW (2026-06-04T11:15:12Z and 2026-07-07T13:00:04Z, several fuels several times too high); `MAX_PLAUSIBLE_GEN_MW` (65 GW) keeps them out of the history and the 24-hour charts.

## Testing locally (safe)

```bash
SCR=<scratch dir>
cp grid_data.db config.json "$SCR"/ && mkdir -p "$SCR/static" && cp static/forecast.json "$SCR/static/"
# then run code with cwd=$SCR (app.py/harvester.py use relative paths), e.g. via PYTHONPATH
```

`app.py` and `harvester.py` use **relative paths** (`grid_data.db`, `config.json`, `static/forecast.json`), so the working directory decides which files they touch. Don't run `harvester.py` from the live folder when testing: it INSERTs into the live DB.
