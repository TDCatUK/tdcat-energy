# TDCat Energy Dashboard

A live dashboard for the GB electricity grid and a home Tesla Powerwall, served at **energy.tdcat.com**.

- **Grid:** generation mix, demand, interconnector flows, frequency, carbon intensity, and balancing/market prices from Elexon BMRS, NESO, Sheffield Solar PV_Live and the Carbon Intensity API.
- **Home:** Powerwall solar, home load, battery and grid flows, Octopus Agile import/export rates and yesterday's meter readings.
- **Weather:** current conditions and a 7-day forecast from Open-Meteo.

## How it runs

| Piece | What it does |
|---|---|
| `harvester.py` | Runs every 5 min on OTTO. Calls all the APIs and appends one row to `grid_data.db`. Writes `static/forecast.json`. |
| `app.py` | Flask app on port 5000. Serves the pages and `/api/data` (the last 288 rows, about 24 h) and `/api/config`. |
| `static/script.js` | All the front-end rendering and charts (Chart.js). |
| `templates/` | `index.html` (dashboard), `admin.html` (colours/thresholds editor), `about.html`. |
| `config.json` | Theme and threshold settings, edited from `/admin`. |

Secrets live in `.env` and `.powerwall`, which are not committed. See `CLAUDE.md` for full details.

## Changes

### 2026-10-06
- Put the project under git and backed it up to GitHub (`TDCatUK/tdcat-energy`).
- Added `.gitignore` to keep secrets, the virtualenv, caches and live data out of the repo.
- Added this README and `CLAUDE.md` (handover notes).
- Octopus data is working again with the new API key (it had been 0 since 30 Sep, 16:55 UTC). Confirmed on the 12:00 UTC harvester run.
- Moved old one-off and test scripts into `archive/`. The two with hard-coded credentials stay there but aren't committed.
- **Maths fixes, part 1 (harvester and API):**
  - Demand breakdown: "Transmission" now really is ITSDO. Solar and LV wind were being counted twice, which made Transmission, National, Net and Gross about 6 GW too high around midday. Checked against Elexon's own ITSDO and INDO.
  - Generation mix: pumped storage while pumping no longer shows as a negative share or reduces total generation. Mix percentages always add up to 100%, and charts now use MW values directly.
  - Home "today" totals start at UK midnight, not UTC midnight (BST was missing the first hour).
  - Octopus daily figures cover one whole UK day that's complete on all three meters, so the date label is true for import, export and gas.
  - Market index price no longer drops to £0 just after midnight, and zero-volume placeholder prices are ignored.
  - Carbon intensity falls back to the forecast when the actual figure isn't published yet.
  - Greenlink (Ireland) interconnector named properly and counted in the Ireland flow.
  - Demand breakdown label now reads "Embedded (Solar + LV Wind)".
- **Maths fixes, part 2 (dashboard), live after the Flask restart on OTTO:**
  - The generation history, single-fuel chart and demand-breakdown chart use the API's MW figures directly, instead of rebuilding them from percentages.
  - The flow diagram's Demand node is now National + embedded (what GB actually uses), so supply and demand balance.
  - Greenlink added to the interconnector capacity list (0.5 GW).
- Battery % now matches the Tesla app: (raw − 5) / 0.95, because the app hides a 5% reserve. The database still stores the raw gateway figure, so history stays consistent.
- Cleaned up `harvester.log`: fixed the `utcnow()` deprecation warnings at the source, moved the old log (23 Apr – 6 Oct) to `archive/harvester-2026-04-23_to_2026-10-06.log.gz`, and started a fresh log.
- `harvester.log` now keeps only the last 90 days. The harvester trims older entries itself, about once a day, so the log stays around 2–3 MB.
- Removed files not in use: five April database backups, the `archive/` folder (old one-off and test scripts, including two with hard-coded credentials, and the old log archive), and `.DS_Store`. The committed scripts can still be recovered from git history.
- New **Grid Batteries** panel (unofficial estimate): GB grid-scale battery charging and discharging, worked out every 5 minutes from Balancing Mechanism data (each battery's Physical Notification, updated with NESO's Bid-Offer Acceptances). Two new database columns: `bess_discharge_mw` and `bess_charge_mw`.
- Rewrote the About page: corrected the demand definitions, frequency limits, imbalance price, market index, Octopus and Powerwall descriptions, and the "dashed line" explanation; changed UK to GB where it means the grid; added sections on the battery estimate and how the battery % matches the Tesla app.
- Grid Batteries: backfilled the last 24 hours of estimates (from 5 Oct, 14:35 UTC) using the same calculation as the live harvester, and fixed the chart's axis labels (they showed values like -0.2000000000000002 GW).
- **Security fix:** the settings save no longer goes to the public `/api/config`, which accepted changes with no login. It now goes to `/admin/api/config`, which the Cloudflare Access login on `/admin/*` protects. `/api/config` is now read-only, saves are checked before writing, and `config.json` is replaced in one step so a failed save can't corrupt it.
- New **National Gas Data** section: linepack, total supply and demand, where gas is coming from (North Sea, Norway's Langeled pipeline, LNG, storage, continental pipelines), where it's going (homes & businesses, power stations, industry, exports, storage injection), storage and LNG stock levels, a rough gas-for-power efficiency figure, and a 24-hour chart. Data from the National Gas Transmission data portal, collected every 5 minutes into a new `gas_snapshots` table. About page updated to explain it.
- Gas storage history: the harvester now keeps daily storage, LNG and Rough stock levels in a new `gas_storage_daily` table, back-filled to May 2020 on its first run. The Storage card compares today's stock with the same date over the previous five years and turns red, amber or green accordingly; it has a 12-month sparkline, and clicking it opens a chart of this year against each previous year. One-off glitches in National Gas's published history (zeros and impossible jumps) are skipped when reading.
- Gas chart colours and the storage thresholds can now be changed on the admin page. Fuel colours are saved from whatever fuels the page shows, so new ones (like batteries) aren't dropped, and the admin page now reports a failed save instead of always saying "Saved".
- The 24-Hour Generation Mix can show the battery estimate as its own band (discharging only). It's on by default, the "Batteries (est.)" button turns it off, and the browser remembers the choice. % mode is now calculated in the browser so it adds up to 100% either way. Batteries are also an option in the single-fuel chart.
- The Frequency card turns the limit colour when frequency is outside the operational limits set on the admin page.
- Batteries now appear in all the generation views when the "Batteries (est.)" switch is on: a slice in Generation by Fuel Type, a band in the 24-Hour Generation Mix, and in the Live Energy Flow. The flow's Storage node is now two-way: pumped storage and batteries combined into one net flow, with the dots reversing when storage is discharging overall, and a hover breakdown. Pumped-storage generation moved from HV Gen to Storage, so Total Output now equals the sum of its inflows. The switch is an On/Off pill on both the Generation by Fuel Type and 24-Hour Generation Mix headers.
- Moved the Grid Batteries panel to just below the 24-Hour Generation Mix.
- New Changelog page (`/changelog`, linked in the top menu) summarising changes for visitors.
- Live Energy Flow: batteries now have their own node at the top (opposite Imports), and the right-hand node is pumped hydro only ("generating"/"pumping"), each showing its own net flow and hover breakdown. The battery node dims to "Off" when the estimate is switched off. New `flow.icons.batt` setting (admin); `config.json` now uses a water icon for pumped hydro and the battery icon for batteries. The direction text is smaller so it no longer touches the circle.
- Changelog page made compact (one card per date, New and Fixed side by side), written in the first person, with the Security, Behind the scenes and admin-only items removed.
- New **When Demand Shifts** panel: unsmoothed half-hourly national demand around the end of off-peak (morning), the evening climb as solar fades, and the start of off-peak (night). Each card shows the last 30 days, their average and the latest day, plus bars of the half-hour-to-half-hour change, with a computed summary. Off-peak times are set on the admin page (`patterns` in config).
- New **Duck Curve** card: average daily demand shape for any month, every five years since 2010 plus the latest two years and the last 30 days, with rooftop solar added back for the latest year and facts on the record solar share and when solar first out-produced the grid's own demand (2026).
- Data comes from NESO (Demand Data Update every 3 hours; yearly Historic Demand Data daily, back-filled to 2010 on first run) into new `neso_demand_hh`, `duck_profiles`, `duck_records` and `fetch_log` tables.
- Solar records and the duck curve's current year now combine NESO's yearly file (a few weeks behind) with the daily Demand Data Update for every day after the file ends, so new records appear within a day without double counting. A record set in the last two weeks gets a "New record" badge. The duck chart and its facts also refresh hourly with the recent data.
- **Frequency in full detail:** the harvester now keeps every 15-second frequency reading from Elexon (same single request per run, so no extra load) in a new `frequency_readings` table, and back-fills a week per run to 23 Apr 2026. Clicking the Frequency card opens a chart of every reading for the last 1, 6 or 24 hours, with today's low and high (and when), time spent outside the operational limits and the legal 49.5–50.5 Hz limits, and the number of readings. The card also shows today's range. New endpoint `/api/frequency?hours=`.
- New **Coming Up: Agile Prices & Carbon** section: Octopus Agile import and export rates for every published half-hour (tomorrow's appear about 4pm) and the national carbon intensity forecast for 48 hours, with the cheapest, most expensive and greenest 3-hour runs and the cheapest half-hour picked out. The harvester fetches both every 30 minutes into new `agile_rates` and `carbon_forecast` tables; new endpoint `/api/forecast`.
- New **Status** page (`/status`, in the menu with a green/amber/red dot): every data source's state, when it last worked, how recent its data is, the reason for any failure (no URLs or response bodies, which can contain meter numbers), 7-day and 24-hour success rates and an hour-by-hour bar for the last 7 days, plus the harvester's last run and run time. The harvester now reports each source's result on every run into new `source_status` and `source_runs` tables (runs kept 90 days). `fetch_octo_rate()` now returns None on failure, so a failed fetch is told apart from a real 0p rate (the database still stores 0). New endpoint `/api/status` (`?summary=1` for the menu dot).
- New **History** page (`/history`, in the menu and linked from the 24-Hour Generation Mix): 7 days of hourly averages, or 30 days / 1 year of daily (UK-day) averages for the generation mix (GW or %, with demand), carbon intensity, market index price (with range) and Agile import, frequency (hourly/daily range and minutes outside the limits, from the 15-second readings), interconnector net flow and Powerwall energy, plus a summary (average/peak/lowest demand, wind/solar/low-carbon shares, greenest and cheapest periods, frequency time outside limits, home totals). `app.py` folds every snapshot into hourly sums in memory using `summarise_row()` (about 1 s after a Flask restart, then topped up incrementally), skipping zeros that were stored for failed fetches. New endpoint `/api/history?range=7d|30d|1y`; front end in `static/history.js`.
- Rows whose generation adds up to more than 65 GW (two Elexon glitches: 4 Jun 11:15 and 7 Jul 13:00 UTC, 334–377 GW) are now skipped in the history and replaced by the previous row in the live 24-hour charts.
