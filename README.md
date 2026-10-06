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
