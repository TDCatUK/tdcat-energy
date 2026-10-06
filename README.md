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
- Moved old one-off and test scripts into `archive/`. The two with hard-coded credentials stay there but aren't committed.
