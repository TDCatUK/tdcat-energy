import os
import requests
import sqlite3
import json
from datetime import datetime, timedelta, timezone
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
NESO_EMBEDDED_URL = os.getenv("NESO_EMBEDDED_URL") # NEW URL FOR EMBEDDED WIND
ELEXON_DEMAND_URL = os.getenv("ELEXON_DEMAND_URL")
ELEXON_SYSTEM_PRICE_URL = os.getenv("ELEXON_SYSTEM_PRICE_URL")
ELEXON_MARKET_INDEX_URL = os.getenv("ELEXON_MARKET_INDEX_URL")
ELEXON_FREQUENCY_URL = os.getenv("ELEXON_FREQUENCY_URL")
CARBON_INTENSITY_URL = os.getenv("CARBON_INTENSITY_URL")
SHEFFIELD_SOLAR_URL = os.getenv("SHEFFIELD_SOLAR_URL")
WEATHER_URL = os.getenv("WEATHER_URL")

# === Cloudflare ===
CLOUDFLARE_API_TOKEN = os.getenv("CLOUDFLARE_API_TOKEN")
CLOUDFLARE_ZONE_ID = os.getenv("CLOUDFLARE_ZONE_ID")
HOSTNAME = "energy.tdcat.com"


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

    now = datetime.utcnow()
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
        period_from = (now_utc - timedelta(hours=3)).strftime('%Y-%m-%dT%H:%M:%SZ')
        period_to   = (now_utc + timedelta(hours=8)).strftime('%Y-%m-%dT%H:%M:%SZ')

        params = {
            'period_from': period_from,
            'period_to': period_to,
            'page_size': 100
        }

        res = requests.get(url, auth=(OCT_KEY, ''), params=params, timeout=timeout)
        res.raise_for_status()
        data = res.json()

        if 'results' in data and data['results']:
            for rate in data['results']:
                vf_str = rate.get('valid_from')
                vt_str = rate.get('valid_to')
                if not vf_str:
                    continue

                vf = datetime.fromisoformat(vf_str.replace('Z', '+00:00'))
                if vt_str:
                    vt = datetime.fromisoformat(vt_str.replace('Z', '+00:00'))
                else:
                    vt = vf + timedelta(minutes=30)

                if vf <= now_utc < vt:
                    value = float(rate.get('value_inc_vat', 0))
                    return value

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

def fetch_octo_consumption(meter_id, serial, meter_type="electricity", timeout=20):
    if not OCTOPUS_BASE_URL or not meter_id or not serial: return 0, ""
    url = f"{OCTOPUS_BASE_URL.rstrip('/')}/{meter_type}-meter-points/{meter_id}/meters/{serial}/consumption/"
    try:
        res = requests.get(url, auth=(OCT_KEY, ''), params={'page_size': 48}, timeout=timeout).json()
        if 'results' in res and len(res['results']) > 0:
            total = sum(item['consumption'] for item in res['results'])
            raw_date = res['results'][0]['interval_start'][:10]
            parsed_date = datetime.strptime(raw_date, '%Y-%m-%d')
            return total, parsed_date.strftime('%d %b')
    except: pass
    return 0, ""


def fetch_and_store():
    print(f"[{datetime.utcnow().strftime('%Y-%m-%d %H:%M:%S')}] Harvesting live data...")

    try:
        req_timeout = 20
        now_utc = datetime.now(timezone.utc)

        # === OCTOPUS API ===
        oct_imp_pence = fetch_octo_rate(OCT_IMP_TARIFF, now_utc, req_timeout)
        oct_exp_pence = fetch_octo_rate(OCT_EXP_TARIFF, now_utc, req_timeout)
        oct_yest_imp, oct_date_imp = fetch_octo_consumption(OCT_IMP_MPAN, OCT_SERIAL, "electricity", req_timeout)
        oct_yest_exp, _ = fetch_octo_consumption(OCT_EXP_MPAN, OCT_SERIAL, "electricity", req_timeout)
        oct_yest_gas, oct_date_gas = fetch_octo_consumption(OCT_GAS_MPRN, OCT_GAS_SERIAL, "gas", req_timeout)
        oct_final_date = oct_date_imp if oct_date_imp else oct_date_gas

        # === WEATHER API ===
        try:
            if not WEATHER_URL:
                raise ValueError("WEATHER_URL not set in .env")

            resp = requests.get(WEATHER_URL, timeout=req_timeout)
            resp.raise_for_status()
            weather_res = resp.json()

            if weather_res.get("error"):
                raise ValueError(f"Open-Meteo API error: {weather_res.get('reason')}")

            current = weather_res.get('current', {})
            daily   = weather_res.get('daily',   {})

            temp_c       = current.get('temperature_2m') or 0
            wind_mph     = current.get('wind_speed_10m') or 0
            cloud_cover  = current.get('cloud_cover') or 0

            daylight_list = daily.get('daylight_duration', [0])
            daylight_secs = daylight_list[0] if daylight_list else 0

        except Exception as e:
            print(f"Weather fetch failed: {type(e).__name__}: {e}")
            temp_c = wind_mph = cloud_cover = daylight_secs = 0

        # === CARBON API ===
        try:
            ci_res = requests.get(CARBON_INTENSITY_URL, timeout=req_timeout).json() if CARBON_INTENSITY_URL else {}
            carbon_intensity = ci_res.get('data', [{}])[0].get('intensity', {}).get('actual', 0)
            if carbon_intensity is None: carbon_intensity = 0
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

        # === EMBEDDED WIND API ===
        embedded_wind_mw = 0
        try:
            if NESO_EMBEDDED_URL:
                emb_res = requests.get(NESO_EMBEDDED_URL, timeout=req_timeout).json()
                
                # NESO CKAN API returns data inside 'result' -> 'records'
                records = emb_res.get('result', {}).get('records', [])
                if records:
                    latest_record = records[0]
                    # Extract the specific column
                    embedded_wind_mw = int(latest_record.get('EMBEDDED_WIND_GENERATION', 0))
        except Exception as e:
            print(f"Embedded fetch error: {e}")


        # === GENERATION MIX API ===
        generation, interconnectors, total_net_flow, total_generation = {}, [], 0, 0
        try:
            gen_res = requests.get(ELEXON_GEN_URL, timeout=req_timeout).json() if ELEXON_GEN_URL else {}
            if gen_res.get('data'):
                latest_time = max(item['publishTime'] for item in gen_res['data'])
                current_mix = [item for item in gen_res['data'] if item['publishTime'] == latest_time]

                # Updated fuel mapping to distinguish HV wind
                fuel_mapping = {"CCGT": "Combined Cycle Gas (CCGT)", "WIND": "Wind (HV)", "NUCLEAR": "Nuclear", "BIOMASS": "Biomass", "COAL": "Coal", "NPSHYD": "Hydro", "PS": "Pumped Storage", "OCGT": "Open Cycle Gas", "OTHER": "Other"}
                interconnector_mapping = {"INTFR": "France (IFA)", "INTIFA2": "France (IFA2)", "INTELEC": "France (ElecLink)", "INTNED": "Netherlands (BritNed)", "INTIRL": "Ireland (Moyle)", "INTEW": "Ireland (EWIC)", "INTNEM": "Belgium (Nemo)", "INTNSL": "Norway (NSL)", "INTVKL": "Denmark (Viking)"}

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
                if embedded_wind_mw > 0: generation["Wind (Embedded)"] = int(embedded_wind_mw)
                total_generation = sum(generation.values())
        except: pass

        true_demand = latest_demand + (solar_mw if solar_mw > 0 else 0)

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
                start_of_day = now_utc.replace(hour=0, minute=0, second=0, microsecond=0)
                end_time = (now_utc + timedelta(hours=3)).strftime('%Y-%m-%dT%H:%M:%SZ')
                res = requests.get(ELEXON_MARKET_INDEX_URL, params={
                    'from': start_of_day.strftime('%Y-%m-%dT%H:%M:%SZ'),
                    'to': end_time,
                }, timeout=req_timeout)

                if res.status_code == 200:
                    data = res.json().get('data', [])
                    if data:
                        data.sort(key=lambda x: x.get('startTime', ''), reverse=True)
                        now_str = now_utc.strftime('%Y-%m-%dT%H:%M:%SZ')
                        
                        current_period_data = [item for item in data if item.get('startTime', '') <= now_str][:6]

                        apx_price = n2ex_price = 0.0
                        for item in current_period_data:
                            provider = item.get('dataProvider')
                            p = float(item.get('price', 0) or 0)
                            
                            if provider == "APXMIDP" and apx_price == 0.0:
                                apx_price = p
                            elif provider == "N2EXMIDP" and n2ex_price == 0.0:
                                n2ex_price = p

                        latest_market_index_price = apx_price if apx_price > 0 else n2ex_price
                        latest_day_ahead_price = n2ex_price if n2ex_price > 0 else apx_price
                        
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
            cf_visits, cf_requests, cf_bytes, embedded_wind_mw
        ))
        conn.commit()
        conn.close()
        print(f"-> Success! Row added.")

    except Exception as e:
        print(f"-> Harvester Error: {e}")


if __name__ == '__main__':
    fetch_and_store()