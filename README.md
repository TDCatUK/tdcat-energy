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
