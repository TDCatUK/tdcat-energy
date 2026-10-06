import os
import sys
import requests
import sqlite3
import json
from datetime import datetime, timedelta, timezone, time
from zoneinfo import ZoneInfo
import pypowerwall
from dotenv import load_dotenv

load_dotenv()

# === ENVIRONMENT VARIABLES ===
PW_IP = os.getenv("PW_IP")
PW_EMAIL = os.getenv("PW_EMAIL")
PW_PASSWORD = os.getenv("PW_PASSWORD")

OCT_KEY = os.getenv("OCTOPUS_API_KEY")
OCT_REGION = os.getenv("OCT_REGION")
OCT_IMP_TARIFF = os.getenv("OCT_IMPORT_TARIFF")
OCT_EXP_TARIFF = os.getenv("OCT_EXPORT_TARIFF")
OCT_IMP_MPAN = os.getenv("OCT_ELEC_MPAN")
OCT_EXP_MPAN = os.getenv("OCT_EXPORT_MPAN")
OCT_SERIAL = os.getenv("OCT_ELEC_SERIAL")
OCT_GAS_MPRN = os.getenv("OCT_GAS_MPRN")
OCT_GAS_SERIAL = os.getenv("OCT_GAS_SERIAL")

OCTOPUS_BASE_URL = os.getenv("OCTOPUS_BASE_URL")
ELEXON_GEN_URL = os.getenv("ELEXON_GEN_URL")
ELEXON_DEMAND_URL = os.getenv("ELEXON_DEMAND_URL")
ELEXON_SYSTEM_PRICE_URL = os.getenv("ELEXON_SYSTEM_PRICE_URL")
ELEXON_MARKET_INDEX_URL = os.getenv("ELEXON_MARKET_INDEX_URL")
ELEXON_FREQUENCY_URL = os.getenv("ELEXON_FREQUENCY_URL")
CARBON_INTENSITY_URL = os.getenv("CARBON_INTENSITY_URL")
SHEFFIELD_SOLAR_URL = os.getenv("SHEFFIELD_SOLAR_URL")
WEATHER_URL = os.getenv("WEATHER_URL")
NESO_EMBEDDED_URL = os.getenv("NESO_EMBEDDED_URL")

# === Cloudflare ===
CLOUDFLARE_API_TOKEN = os.getenv("CLOUDFLARE_API_TOKEN")
CLOUDFLARE_ZONE_ID = os.getenv("CLOUDFLARE_ZONE_ID")
HOSTNAME = "energy.tdcat.com"

LONDON = ZoneInfo("Europe/London")


def get_cloudflare_stats(debug=False):
    """Fetch last ~24h Cloudflare stats (visits, requests, bytes) for energy.tdcat.com"""
    if not CLOUDFLARE_API_TOKEN or not CLOUDFLARE_ZONE_ID:
        if debug:
            print("Cloudflare: Missing API token or Zone ID in .env")
        return 0, 0, 0

    url = "https://api.cloudflare.com/client/v4/graphql"
    headers = {
        "Authorization": f"Bearer {CLOUDFLARE_API_TOKEN}",
        "Content-Type": "application/json"
    }

    now = datetime.now(timezone.utc)
    start = (now - timedelta(days=1)).strftime('%Y-%m-%dT%H:%M:%SZ')
    end = now.strftime('%Y-%m-%dT%H:%M:%SZ')

    query = f"""
    query {{
      viewer {{
        zones(filter: {{ zoneTag: "{CLOUDFLARE_ZONE_ID}" }}) {{
          httpRequestsAdaptiveGroups(
            limit: 100,
            filter: {{
              clientRequestHTTPHost: "{HOSTNAME}",
              datetime_geq: "{start}",
              datetime_lt: "{end}"
            }}
          ) {{
            count
            sum {{ visits, edgeResponseBytes }}
            dimensions {{ datetimeHour }}
          }}
        }}
      }}
    }}
    """

    try:
        response = requests.post(url, headers=headers, json={'query': query}, timeout=15)
        response.raise_for_status()
        data = response.json()

        if data.get('errors'):
            if debug:
                print("Cloudflare GraphQL Errors:", data['errors'])
            return 0, 0, 0

        groups = (data.get('data', {})
                    .get('viewer', {})
                    .get('zones', [{}])[0]
                    .get('httpRequestsAdaptiveGroups', []))

        if not groups:
            return 0, 0, 0

        total_visits = sum(g.get('sum', {}).get('visits', 0) for g in groups)
        total_requests = sum(g.get('count', 0) for g in groups)
        total_bytes = sum(g.get('sum', {}).get('edgeResponseBytes', 0) for g in groups)

        if debug:
            print(f"Cloudflare → {total_visits} visits, {total_requests} requests, {total_bytes:,} bytes (last 24h)")

        return total_visits, total_requests, total_bytes

    except Exception as e:
        if debug:
            print(f"Cloudflare API error: {e}")
        return 0, 0, 0

def fetch_octo_rate(tariff_code, now_utc, timeout=20):
    if not OCTOPUS_BASE_URL or not tariff_code:
        return 0.0

    url = f"{OCTOPUS_BASE_URL.rstrip('/')}/products/{tariff_code}/electricity-tariffs/E-1R-{tariff_code}-{OCT_REGION}/standard-unit-rates/"

    try:
        # === WIDER WINDOW (the key fix) ===
        # Covers several half-hour slots in both directions — extremely reliable
        period_from = (now_utc - timedelta(hours=3)).strftime('%Y-%m-%dT%H:%M:%SZ')
        period_to   = (now_utc + timedelta(hours=8)).strftime('%Y-%m-%dT%H:%M:%SZ')

        params = {
            'period_from': period_from,
            'period_to': period_to,
            # page_size is optional but helps when the window is wide
            'page_size': 100
        }

        res = requests.get(url, auth=(OCT_KEY, ''), params=params, timeout=timeout)
        res.raise_for_status()          # catch HTTP errors properly
        data = res.json()

        if 'results' in data and data['results']:
            for rate in data['results']:
                vf_str = rate.get('valid_from')
                vt_str = rate.get('valid_to')
                if not vf_str:
                    continue

                # Better parsing that produces timezone-aware datetimes
                # (handles the 'Z' correctly and avoids naive-vs-aware comparison bugs)
                vf = datetime.fromisoformat(vf_str.replace('Z', '+00:00'))
                if vt_str:
                    vt = datetime.fromisoformat(vt_str.replace('Z', '+00:00'))
                else:
                    vt = vf + timedelta(minutes=30)  # standard half-hourly slot

                if vf <= now_utc < vt:
                    value = float(rate.get('value_inc_vat', 0))
                    # Optional debug line (remove or comment out in production)
                    # print(f"✓ Octopus {tariff_code}: {value:.2f} p/kWh  [{vf} → {vt}]")
                    return value

            # Debug helper — shows what the API actually returned
            print(f"Octopus {tariff_code}: No matching rate in window (got {len(data['results'])} periods)")
        else:
            print(f"Octopus {tariff_code}: Empty results from API")

    except requests.exceptions.RequestException as e:
        print(f"Octopus rate HTTP error ({tariff_code}): {e}")
        if 'res' in locals():
            print(f"   Status: {res.status_code}  Body: {res.text[:400]}")
    except Exception as e:
        print(f"Octopus rate parse error ({tariff_code}): {e}")

    return 0.0

def fetch_octo_day_totals(meter_id, serial, meter_type, start, end, timeout=20):
    """Consumption between start and end, summed per UK day: {date: (total, half_hours)}."""
    url = f"{OCTOPUS_BASE_URL.rstrip('/')}/{meter_type}-meter-points/{meter_id}/meters/{serial}/consumption/"
    res = requests.get(url, auth=(OCT_KEY, ''), params={
        'period_from': start.strftime('%Y-%m-%dT%H:%M:%SZ'),
        'period_to': end.strftime('%Y-%m-%dT%H:%M:%SZ'),
        'page_size': 500
    }, timeout=timeout).json()
    days = {}
    for item in res.get('results', []):
        day = datetime.fromisoformat(item['interval_start'].replace('Z', '+00:00')).astimezone(LONDON).date()
        total, slots = days.get(day, (0, 0))
        days[day] = (total + item['consumption'], slots + 1)
    return days

def fetch_octo_daily(timeout=20):
    """Import, export and gas totals for the most recent UK day that's complete on every meter.

    Export and gas readings usually reach Octopus a day after import, so this is often two days ago.
    One shared day keeps the single date label on the dashboard true for all three figures.
    """
    if not OCTOPUS_BASE_URL: return 0, 0, 0, ""
    today = datetime.now(LONDON).date()
    uk_midnight = lambda d: datetime.combine(d, time.min, LONDON).astimezone(timezone.utc)
    meters = [(OCT_IMP_MPAN, OCT_SERIAL, "electricity"), (OCT_EXP_MPAN, OCT_SERIAL, "electricity"), (OCT_GAS_MPRN, OCT_GAS_SERIAL, "gas")]
    per_meter = []
    for meter_id, serial, meter_type in meters:
        if not meter_id or not serial:
            per_meter.append(None)
            continue
        try:
            per_meter.append(fetch_octo_day_totals(meter_id, serial, meter_type, uk_midnight(today - timedelta(days=3)), uk_midnight(today), timeout))
        except Exception as e:
            print(f"Octopus consumption error ({meter_type} {meter_id[-4:]}): {e}")
            per_meter.append({})

    def complete(days, day):
        expected = int((uk_midnight(day + timedelta(days=1)) - uk_midnight(day)).total_seconds() // 1800)  # 46 / 48 / 50
        return days.get(day, (0, 0))[1] >= expected

    candidates = [today - timedelta(days=n) for n in (1, 2, 3)]
    chosen = next((d for d in candidates if all(m is None or complete(m, d) for m in per_meter)), None)
    if chosen is None:
        # A meter has stopped reporting: fall back to the latest day with complete import data
        chosen = next((d for d in candidates if per_meter[0] and complete(per_meter[0], d)), None)
    if chosen is None: return 0, 0, 0, ""
    imp, exp, gas = (m.get(chosen, (0, 0))[0] if m else 0 for m in per_meter)
    return imp, exp, gas, chosen.strftime('%d %b')


LOG_FILE = 'harvester.log'
LOG_KEEP_DAYS = 90

def log_time(line):
    """UTC time from a b'[YYYY-MM-DD HH:MM:SS] Harvesting...' line, else None."""
    if line[:1] == b'[' and line[20:21] == b']':
        try: return datetime.strptime(line[1:20].decode('ascii'), '%Y-%m-%d %H:%M:%S')
        except ValueError: pass
    return None

def trim_log():
    """Keep only the last LOG_KEEP_DAYS days of harvester.log.

    The scheduler on OTTO appends this script's output to the log, so it's rewritten
    in place (same file), never replaced. Does nothing unless stdout really is that
    file, so test runs can't touch the live log. Most runs only read the first entry;
    a trim happens once the oldest entry is a day past the limit. Binary mode keeps
    the kept lines byte-for-byte (some logged error pages contain CRLFs).
    """
    try:
        if not os.path.exists(LOG_FILE) or not os.path.samestat(os.fstat(sys.stdout.fileno()), os.stat(LOG_FILE)):
            return
        cutoff = datetime.now(timezone.utc).replace(tzinfo=None) - timedelta(days=LOG_KEEP_DAYS)
        with open(LOG_FILE, 'r+b') as f:
            oldest = None
            while oldest is None:
                line = f.readline()
                if not line: return
                oldest = log_time(line)
            if oldest >= cutoff - timedelta(days=1): return
            f.seek(0)
            lines = f.readlines()
            keep_from = next((i for i, line in enumerate(lines) if (t := log_time(line)) and t >= cutoff), len(lines))
            f.seek(0)
            f.writelines(lines[keep_from:])
            f.truncate()
        print(f"Trimmed {LOG_FILE} to the last {LOG_KEEP_DAYS} days ({keep_from} old lines removed)")
    except Exception as e:
        print(f"Log trim error: {e}")


def fetch_and_store():
    print(f"[{datetime.now(timezone.utc).strftime('%Y-%m-%d %H:%M:%S')}] Harvesting live data...")

    try:
        req_timeout = 20
        now_utc = datetime.now(timezone.utc)

        # === OFFLINE / LOCAL-ONLY MODE ===
        try:
            # Check if the wider internet is alive
            requests.get("https://1.1.1.1", timeout=5)
        except requests.exceptions.RequestException:
            print("-> ISP Offline. Switching to Local-Only mode (Forward-Filling Grid Data).")
            
            try:
                # 1. Get the last known good row from the DB
                conn = sqlite3.connect('grid_data.db')
                conn.row_factory = sqlite3.Row
                cursor = conn.cursor()
                cursor.execute('SELECT * FROM energy_snapshots ORDER BY timestamp DESC LIMIT 1')
                last_row = cursor.fetchone()
                
                if not last_row:
                    print("No previous data to forward-fill. Aborting.")
                    return
                last = dict(last_row)

                # 2. Fetch LIVE Powerwall Data locally
                pw_solar, pw_home, pw_battery, pw_grid, pw_level, pw_grid_status = 0, 0, 0, 0, 0, "UNKNOWN"
                if PW_IP and PW_PASSWORD:
                    try:
                        pw = pypowerwall.Powerwall(host=PW_IP, password=PW_PASSWORD, email=PW_EMAIL)
                        pw_power = pw.power()
                        if sum(pw_power.values()) != 0 or pw.level() > 0:
                            pw_solar = pw_power.get('solar', 0)
                            pw_home = pw_power.get('load', 0)
                            pw_battery = pw_power.get('battery', 0)
                            pw_grid = pw_power.get('site', 0)
                            pw_level = pw.level()
                            pw_grid_status = pw.grid_status()
                    except Exception as pw_e:
                        print(f"PW Offline too: {pw_e}")

                # 3. Stitch them together and insert
                cursor.execute('''
                    INSERT INTO energy_snapshots 
                    (timestamp, carbon_intensity, demand_mw, total_generation_mw, net_flow_mw, 
                     wholesale_price, day_ahead_price, market_index_price, grid_frequency, net_imbalance_volume, 
                     generation_mix, interconnector_flows, 
                     pw_solar_w, pw_home_w, pw_battery_w, pw_grid_w, pw_level, pw_grid_status, 
                     temp_c, wind_mph, daylight_secs, cloud_cover, 
                     oct_import_pence, oct_export_pence, oct_yest_import, oct_yest_export, 
                     oct_yest_gas, oct_yest_date,
                     cf_visits_24h, cf_requests_24h, cf_bytes_24h, embedded_wind_mw)
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                ''', (
                    now_utc.strftime('%Y-%m-%dT%H:%M:%SZ'), # FRESH TIMESTAMP
                    last.get('carbon_intensity', 0), last.get('demand_mw', 0), last.get('total_generation_mw', 0), last.get('net_flow_mw', 0),
                    last.get('wholesale_price', 0), last.get('day_ahead_price', 0), last.get('market_index_price', 0), last.get('grid_frequency', 50.0), last.get('net_imbalance_volume', 0),
                    last.get('generation_mix', '{}'), last.get('interconnector_flows', '[]'),
                    pw_solar, pw_home, pw_battery, pw_grid, pw_level, pw_grid_status, # FRESH LOCAL DATA
                    last.get('temp_c', 0), last.get('wind_mph', 0), last.get('daylight_secs', 0), last.get('cloud_cover', 0), 
                    last.get('oct_import_pence', 0), last.get('oct_export_pence', 0), last.get('oct_yest_import', 0), last.get('oct_yest_export', 0), 
                    last.get('oct_yest_gas', 0), last.get('oct_yest_date', ''),
                    last.get('cf_visits_24h', 0), last.get('cf_requests_24h', 0), last.get('cf_bytes_24h', 0),
                    last.get('embedded_wind_mw', 0)
                ))
                conn.commit()
                conn.close()
                print("-> Success! Local-Only row added.")
                return # <-- EXITS THE SCRIPT HERE SO EXTERNAL APIS ARE SKIPPED
                
            except Exception as e:
                print(f"-> Local-Only Error: {e}")
                return

        # === NORMAL ONLINE MODE CONTINUES HERE ===
        
        # === OCTOPUS API ===
        oct_imp_pence = fetch_octo_rate(OCT_IMP_TARIFF, now_utc, req_timeout)
        oct_exp_pence = fetch_octo_rate(OCT_EXP_TARIFF, now_utc, req_timeout)
        oct_yest_imp, oct_yest_exp, oct_yest_gas, oct_final_date = fetch_octo_daily(req_timeout)


        # === WEATHER API ===
        try:
            if not WEATHER_URL:
                raise ValueError("WEATHER_URL not set in .env")

            resp = requests.get(WEATHER_URL, timeout=req_timeout)
            resp.raise_for_status()                  # ← catches HTTP 4xx/5xx errors
            weather_res = resp.json()

            # Open-Meteo sometimes returns {"error": true, "reason": "..."}
            if weather_res.get("error"):
                raise ValueError(f"Open-Meteo API error: {weather_res.get('reason')}")

            current = weather_res.get('current', {})
            daily   = weather_res.get('daily',   {})

            temp_c       = current.get('temperature_2m') or 0
            wind_mph     = current.get('wind_speed_10m') or 0
            cloud_cover  = current.get('cloud_cover') or 0

            daylight_list = daily.get('daylight_duration', [0])
            daylight_secs = daylight_list[0] if daylight_list else 0

            # --- NEW: Save the massive forecast payload locally ---
            try:
                # Assuming your static folder is in the same directory as harvester.py
                with open('static/forecast.json', 'w') as f:
                    json.dump(weather_res, f)
            except Exception as e:
                print(f"Could not save forecast.json: {e}")

        except Exception as e:                       # ← now you’ll actually SEE why it fails
            print(f"Weather fetch failed: {type(e).__name__}: {e}")
            try:
                # --- NEW: Forward-fill from the last known database row ---
                conn = sqlite3.connect('grid_data.db')
                conn.row_factory = sqlite3.Row
                last_w = conn.execute('SELECT temp_c, wind_mph, daylight_secs, cloud_cover FROM energy_snapshots ORDER BY timestamp DESC LIMIT 1').fetchone()
                conn.close()
                
                if last_w:
                    temp_c = last_w['temp_c']
                    wind_mph = last_w['wind_mph']
                    daylight_secs = last_w['daylight_secs']
                    cloud_cover = last_w['cloud_cover']
                else:
                    temp_c = wind_mph = cloud_cover = daylight_secs = 0
            except:
                temp_c = wind_mph = cloud_cover = daylight_secs = 0

            

        # === CARBON API ===
        try:
            ci_res = requests.get(CARBON_INTENSITY_URL, timeout=req_timeout).json() if CARBON_INTENSITY_URL else {}
            intensity = ci_res.get('data', [{}])[0].get('intensity', {})
            carbon_intensity = intensity.get('actual')
            if carbon_intensity is None: carbon_intensity = intensity.get('forecast') or 0
        except: carbon_intensity = 0


        # === DEMAND API ===
        try:
            demand_res = requests.get(ELEXON_DEMAND_URL, timeout=req_timeout).json() if ELEXON_DEMAND_URL else {}
            latest_demand = max(demand_res.get('data', [{'demand': 0}]), key=lambda x: x.get('startTime', ''))['demand']
        except: latest_demand = 0


         # === GRID FREQUENCY API ===
        try:
            if not ELEXON_FREQUENCY_URL:
                raise ValueError("ELEXON_FREQUENCY_URL not set in .env")

            from_dt = (now_utc - timedelta(minutes=12)).strftime('%Y-%m-%dT%H:%M:%SZ')
            to_dt   = now_utc.strftime('%Y-%m-%dT%H:%M:%SZ')

            url = f"{ELEXON_FREQUENCY_URL}?from={from_dt}&to={to_dt}"
            
            freq_res = requests.get(url, timeout=req_timeout).json()
            
            data_list = freq_res if isinstance(freq_res, list) else freq_res.get('data', []) if isinstance(freq_res, dict) else []
            
            if data_list:
                data_list.sort(key=lambda x: x.get('measurementTime', ''), reverse=True)
                latest = data_list[0]
                grid_frequency = float(latest.get('frequency') or 50.0)
            else:
                grid_frequency = 50.0

        except Exception as e:
            print(f"Frequency error: {e}")
            grid_frequency = 50.0



        # === SOLAR API ===
        try: solar_mw = requests.get(SHEFFIELD_SOLAR_URL, timeout=req_timeout).json()['data'][0][2] if SHEFFIELD_SOLAR_URL else 0
        except: solar_mw = 0 


        # === EMBEDDED (LV) WIND API ===
        try: 
            now_utc = datetime.now(timezone.utc)
            
            url = 'https://api.neso.energy/api/3/action/datastore_search'
            params = {
                'resource_id': 'db6c038f-98af-4570-ab60-24d71ebd0ae5',
                'limit': 2000,
                'sort': '_id desc'
            }
            wind_res = requests.get(url, params=params, timeout=req_timeout).json()
            records = wind_res.get('result', {}).get('records', [])
            
            parsed_records = []
            for r in records:
                try:
                    date_part = str(r.get('DATE_GMT', ''))[:10] 
                    time_part = str(r.get('TIME_GMT', ''))
                    
                    if not date_part or not time_part: continue
                    if len(time_part) == 5: time_part += ":00" 
                    
                    record_dt = datetime.strptime(f"{date_part} {time_part}", '%Y-%m-%d %H:%M:%S').replace(tzinfo=timezone.utc)
                    parsed_records.append((record_dt, r))
                except:
                    continue
            
            if parsed_records:
                # The Magic Fix: Find the single record whose timestamp is closest to RIGHT NOW.
                # This completely ignores whether NESO deletes old slots or timestamps them in the future!
                closest_record = min(parsed_records, key=lambda x: abs((x[0] - now_utc).total_seconds()))
                raw_val = closest_record[1].get('EMBEDDED_WIND_FORECAST', 0)
                
                embedded_wind_mw = int(float(raw_val)) if raw_val is not None else 0
            else:
                embedded_wind_mw = 0
                
        except Exception as e:
            print(f"LV Wind error: {e}")
            embedded_wind_mw = 0



        # === GENERATION MIX API ===
        generation, interconnectors, total_net_flow, total_generation = {}, [], 0, 0
        try:
            gen_res = requests.get(ELEXON_GEN_URL, timeout=req_timeout).json() if ELEXON_GEN_URL else {}
            if gen_res.get('data'):
                latest_time = max(item['publishTime'] for item in gen_res['data'])
                current_mix = [item for item in gen_res['data'] if item['publishTime'] == latest_time]

                fuel_mapping = {"CCGT": "Combined Cycle Gas (CCGT)", "WIND": "Wind", "NUCLEAR": "Nuclear", "BIOMASS": "Biomass", "COAL": "Coal", "NPSHYD": "Hydro", "PS": "Pumped Storage", "OCGT": "Open Cycle Gas", "OTHER": "Other"}
                interconnector_mapping = {"INTFR": "France (IFA)", "INTIFA2": "France (IFA2)", "INTELEC": "France (ElecLink)", "INTNED": "Netherlands (BritNed)", "INTIRL": "Ireland (Moyle)", "INTEW": "Ireland (EWIC)", "INTNEM": "Belgium (Nemo)", "INTNSL": "Norway (NSL)", "INTVKL": "Denmark (Viking)", "INTGRNL": "Ireland (Greenlink)"}

                for item in current_mix:
                    fuel_code = item['fuelType']
                    mw = item['generation']
                    if fuel_code.startswith('INT'):
                        interconnectors.append({"name": interconnector_mapping.get(fuel_code, fuel_code), "flow": mw})
                        total_net_flow += mw
                    else:
                        label = fuel_mapping.get(fuel_code, fuel_code)
                        generation[label] = generation.get(label, 0) + mw

                if solar_mw > 0: generation["Solar"] = int(solar_mw)
                if embedded_wind_mw > 0: generation["LV Wind"] = int(embedded_wind_mw)
                total_generation = sum(generation.values())
        except: pass

        true_demand = latest_demand + (solar_mw if solar_mw > 0 else 0) + (embedded_wind_mw if embedded_wind_mw > 0 else 0)


        # === WHOLESALE BALANCING PRICE (SYSTEM SELL PRICE) ===
        latest_price = 0.0
        latest_niv = 0.0
        try:
            if ELEXON_SYSTEM_PRICE_URL:
                for days_back in range(2):
                    target_date = (now_utc - timedelta(days=days_back)).strftime('%Y-%m-%d')
                    url = f"{ELEXON_SYSTEM_PRICE_URL.rstrip('/')}/{target_date}"
                    res = requests.get(url, timeout=req_timeout)
                    if res.status_code == 200:
                        data = res.json().get('data', [])
                        if data:
                            data.sort(key=lambda x: int(x.get('settlementPeriod', 0)), reverse=True)
                            item = data[0]
                            latest_price = float(item.get('systemSellPrice', 0) or 0)
                            latest_niv = float(item.get('netImbalanceVolume', 0) or 0)
                            break
        except Exception as e: print(f"System price error: {e}")


        # === DAY-AHEAD & MARKET INDEX PRICES (MIDP PROXY) ===
        latest_day_ahead_price = 0.0
        latest_market_index_price = 0.0
        try:
            if ELEXON_MARKET_INDEX_URL:
                # Look back 6 h so there's always a published period, even just after midnight
                window_start = now_utc - timedelta(hours=6)
                end_time = (now_utc + timedelta(hours=3)).strftime('%Y-%m-%dT%H:%M:%SZ')
                res = requests.get(ELEXON_MARKET_INDEX_URL, params={
                    'from': window_start.strftime('%Y-%m-%dT%H:%M:%SZ'),
                    'to': end_time,
                }, timeout=req_timeout)

                if res.status_code == 200:
                    data = res.json().get('data', [])
                    if data:
                        data.sort(key=lambda x: x.get('startTime', ''), reverse=True)
                        now_str = now_utc.strftime('%Y-%m-%dT%H:%M:%SZ')
                        
                        # A price with zero traded volume is a placeholder 0, not a real price
                        current_period_data = [item for item in data if item.get('startTime', '') <= now_str and (item.get('volume') or 0) > 0]

                        # Use None instead of 0.0 to allow negative and zero prices
                        apx_price = None
                        n2ex_price = None
                        
                        for item in current_period_data:
                            provider = item.get('dataProvider')
                            # Safely handle missing price keys
                            val = item.get('price')
                            if val is None:
                                continue
                            p = float(val)
                            
                            if provider == "APXMIDP" and apx_price is None:
                                apx_price = p
                            elif provider == "N2EXMIDP" and n2ex_price is None:
                                n2ex_price = p

                        # Fallback logic that respects negative numbers
                        latest_market_index_price = apx_price if apx_price is not None else (n2ex_price if n2ex_price is not None else 0.0)
                        # N2EX has had no volume for months, so this is usually 0. Not shown on the dashboard.
                        latest_day_ahead_price = n2ex_price if n2ex_price is not None else 0.0
                        
        except Exception as e:
            print(f"Pricing error: {e}")



        # === POWERWALL API ===
        pw_solar, pw_home, pw_battery, pw_grid, pw_level, pw_grid_status = 0, 0, 0, 0, 0, "UNKNOWN"
        try:
            if PW_IP and PW_PASSWORD:
                pw = pypowerwall.Powerwall(host=PW_IP, password=PW_PASSWORD, email=PW_EMAIL)
                pw_power = pw.power()
                if sum(pw_power.values()) != 0 or pw.level() > 0:
                    pw_solar, pw_home, pw_battery, pw_grid, pw_level, pw_grid_status = pw_power.get('solar', 0), pw_power.get('load', 0), pw_power.get('battery', 0), pw_power.get('site', 0), pw.level(), pw.grid_status()       
        except: pass

        # === CLOUDFLARE API ===
        cf_visits, cf_requests, cf_bytes = get_cloudflare_stats(debug=False)

        # === DATABASE INJECTION ===
        conn = sqlite3.connect('grid_data.db')
        cursor = conn.cursor()
        cursor.execute('''
            INSERT INTO energy_snapshots 
            (timestamp, carbon_intensity, demand_mw, total_generation_mw, net_flow_mw, 
             wholesale_price, day_ahead_price, market_index_price, grid_frequency, net_imbalance_volume, 
            generation_mix, interconnector_flows, 
             pw_solar_w, pw_home_w, pw_battery_w, pw_grid_w, pw_level, pw_grid_status, 
             temp_c, wind_mph, daylight_secs, cloud_cover, 
             oct_import_pence, oct_export_pence, oct_yest_import, oct_yest_export, 
             oct_yest_gas, oct_yest_date,
             cf_visits_24h, cf_requests_24h, cf_bytes_24h, embedded_wind_mw)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        ''', (
            now_utc.strftime('%Y-%m-%dT%H:%M:%SZ'),
            carbon_intensity, true_demand, total_generation, total_net_flow,
            latest_price, latest_day_ahead_price, latest_market_index_price, grid_frequency, latest_niv,
            json.dumps(generation), json.dumps(interconnectors),
            pw_solar, pw_home, pw_battery, pw_grid, pw_level, pw_grid_status,
            temp_c, wind_mph, daylight_secs, cloud_cover, 
            oct_imp_pence, oct_exp_pence, oct_yest_imp, oct_yest_exp, oct_yest_gas, oct_final_date,
            cf_visits, cf_requests, cf_bytes,
            embedded_wind_mw
        ))
        conn.commit()
        conn.close()
        print(f"-> Success! Row added.")

    except Exception as e:
        print(f"-> Harvester Error: {e}")


if __name__ == '__main__':
    trim_log()
    fetch_and_store()