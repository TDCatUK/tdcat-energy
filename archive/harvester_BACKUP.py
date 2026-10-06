import os
import requests
import sqlite3
import json
from datetime import datetime, timedelta
import pypowerwall
from dotenv import load_dotenv

load_dotenv()

# STRICT ENVIRONMENT VARIABLES (NO HARDCODED FALLBACKS)
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
CARBON_INTENSITY_URL = os.getenv("CARBON_INTENSITY_URL")
SHEFFIELD_SOLAR_URL = os.getenv("SHEFFIELD_SOLAR_URL")
WEATHER_URL = os.getenv("WEATHER_URL")

def fetch_octo_rate(tariff_code, now_utc, timeout=20):
    if not OCTOPUS_BASE_URL or not tariff_code: return 0
    url = f"{OCTOPUS_BASE_URL.rstrip('/')}/products/{tariff_code}/electricity-tariffs/E-1R-{tariff_code}-{OCT_REGION}/standard-unit-rates/"
    try:
        params = {
            'period_from': now_utc.strftime('%Y-%m-%dT%H:%M:%SZ'),
            'period_to': (now_utc + timedelta(minutes=1)).strftime('%Y-%m-%dT%H:%M:%SZ')
        }
        res = requests.get(url, auth=(OCT_KEY, ''), params=params, timeout=timeout).json()
        if 'results' in res:
            for rate in res['results']:
                vf = datetime.strptime(rate['valid_from'], '%Y-%m-%dT%H:%M:%SZ')
                vt = datetime.strptime(rate['valid_to'], '%Y-%m-%dT%H:%M:%SZ') if rate['valid_to'] else now_utc + timedelta(hours=1)
                if vf <= now_utc < vt: return rate['value_inc_vat']
    except: pass
    return 0

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
        now_utc = datetime.utcnow()

        # OCTOPUS API
        oct_imp_pence = fetch_octo_rate(OCT_IMP_TARIFF, now_utc, req_timeout)
        oct_exp_pence = fetch_octo_rate(OCT_EXP_TARIFF, now_utc, req_timeout)
        oct_yest_imp, oct_date_imp = fetch_octo_consumption(OCT_IMP_MPAN, OCT_SERIAL, "electricity", req_timeout)
        oct_yest_exp, _ = fetch_octo_consumption(OCT_EXP_MPAN, OCT_SERIAL, "electricity", req_timeout)
        oct_yest_gas, oct_date_gas = fetch_octo_consumption(OCT_GAS_MPRN, OCT_GAS_SERIAL, "gas", req_timeout)
        oct_final_date = oct_date_imp if oct_date_imp else oct_date_gas

        # WEATHER API
        try:
            weather_res = requests.get(WEATHER_URL, timeout=req_timeout).json() if WEATHER_URL else {}
            temp_c = weather_res.get('current', {}).get('temperature_2m', 0)
            wind_mph = weather_res.get('current', {}).get('wind_speed_10m', 0)
            cloud_cover = weather_res.get('current', {}).get('cloud_cover', 0)
            daylight_secs = weather_res.get('daily', {}).get('daylight_duration', [0])[0]
        except: temp_c, wind_mph, cloud_cover, daylight_secs = 0, 0, 0, 0

        # CARBON API
        try:
            ci_res = requests.get(CARBON_INTENSITY_URL, timeout=req_timeout).json() if CARBON_INTENSITY_URL else {}
            carbon_intensity = ci_res.get('data', [{}])[0].get('intensity', {}).get('actual', 0)
            if carbon_intensity is None: carbon_intensity = 0
        except: carbon_intensity = 0
        
        # DEMAND API
        try:
            demand_res = requests.get(ELEXON_DEMAND_URL, timeout=req_timeout).json() if ELEXON_DEMAND_URL else {}
            latest_demand = max(demand_res.get('data', [{'demand': 0}]), key=lambda x: x.get('startTime', ''))['demand']
        except: latest_demand = 0
        
        # SOLAR API
        try: solar_mw = requests.get(SHEFFIELD_SOLAR_URL, timeout=req_timeout).json()['data'][0][2] if SHEFFIELD_SOLAR_URL else 0
        except: solar_mw = 0 

        # GENERATION MIX API
        generation, interconnectors, total_net_flow, total_generation = {}, [], 0, 0
        try:
            gen_res = requests.get(ELEXON_GEN_URL, timeout=req_timeout).json() if ELEXON_GEN_URL else {}
            if gen_res.get('data'):
                latest_time = max(item['publishTime'] for item in gen_res['data'])
                current_mix = [item for item in gen_res['data'] if item['publishTime'] == latest_time]

                fuel_mapping = {"CCGT": "Combined Cycle Gas (CCGT)", "WIND": "Wind", "NUCLEAR": "Nuclear", "BIOMASS": "Biomass", "COAL": "Coal", "NPSHYD": "Hydro", "PS": "Pumped Storage", "OCGT": "Open Cycle Gas", "OTHER": "Other"}
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
                total_generation = sum(generation.values())
        except: pass

        true_demand = latest_demand + (solar_mw if solar_mw > 0 else 0)

        # # WHOLESALE PRICE (SYSTEM SELL PRICE)
        # latest_price = 0
        # try:
        #     if ELEXON_SYSTEM_PRICE_URL:
        #         for days_back in range(2):
        #             target_date = (now_utc - timedelta(days=days_back)).strftime('%Y-%m-%d')
        #             url = f"{ELEXON_SYSTEM_PRICE_URL.rstrip('/')}/{target_date}"
        #             res = requests.get(url, timeout=req_timeout)
        #             if res.status_code == 200:
        #                 data = res.json().get('data', [])
        #                 if data:
        #                     data.sort(key=lambda x: x.get('settlementPeriod', 0))
        #                     latest_price = data[-1].get('systemSellPrice', 0)
        #                     break
        # except Exception as e: print(f"Sys price error: {e}")https://grok.com/c/60d9a275-362b-4bb8-9b2a-37dd81d10e21?rid=899657ee-8f10-46a4-96a4-24783df2112a

                # === WHOLESALE / BALANCING PRICE — System Sell Price (SSP) ===
        # This is the real-time indicative balancing/imbalance price used for cash-out
        latest_price = 0.0
        source_info = "None"   # for debugging: shows which date/period was used

        try:
            if not ELEXON_SYSTEM_PRICE_URL:
                print("Warning: ELEXON_SYSTEM_PRICE_URL is not configured")
            else:
                # Always try today first, then yesterday (more logical order)
                for days_back in range(2):
                    target_date = (now_utc - timedelta(days=days_back)).strftime('%Y-%m-%d')
                    url = f"{ELEXON_SYSTEM_PRICE_URL.rstrip('/')}/{target_date}"
                    
                    res = requests.get(url, timeout=req_timeout)
                    
                    if res.status_code == 200:
                        data = res.json().get('data', [])
                        if data:
                            # Sort descending by settlementPeriod → newest published period first
                            data.sort(key=lambda x: int(x.get('settlementPeriod', 0)), reverse=True)
                            item = data[0]
                            
                            latest_price = float(item.get('systemSellPrice', 0) or 0)
                            period = item.get('settlementPeriod')
                            source_info = f"{target_date} period {period}"
                            break  # Success — stop looking
                        else:
                            print(f"System price: No data returned for {target_date}")
                    # Quietly skip common "no data yet" codes; log anything unexpected
                    elif res.status_code not in (404, 204):
                        print(f"System price warning — {target_date}: HTTP {res.status_code} {res.text[:120]}")
                        
        except requests.exceptions.Timeout:
            print("System price request timed out")
        except requests.exceptions.RequestException as e:
            print(f"System price network error: {e}")
        except Exception as e:
            print(f"System price unexpected error: {e}")


        # DAY-AHEAD MARKET PRICE
        latest_day_ahead_price = 0
        try:
            if ELEXON_MARKET_INDEX_URL:
                # Wider window: start of today → now + buffer (Day-Ahead prices are known well in advance)
                start_of_day = now_utc.replace(hour=0, minute=0, second=0, microsecond=0)
                end_time = (now_utc + timedelta(hours=1)).strftime('%Y-%m-%dT%H:%M:%SZ')
                
                params = {
                    'from': start_of_day.strftime('%Y-%m-%dT%H:%M:%SZ'),
                    'to': end_time,
                    'dataProviders': 'APXMIDP'   # Use 'N2EXMIDP' if you prefer the other index
                }
                
                res = requests.get(ELEXON_MARKET_INDEX_URL, params=params, timeout=req_timeout)
                
                if res.status_code == 200:
                    data = res.json().get('data', [])
                    if data:
                        # Sort by startTime (most recent first) and take the latest that has started
                        data.sort(key=lambda x: x.get('startTime', ''), reverse=True)
                        now_str = now_utc.strftime('%Y-%m-%dT%H:%M:%SZ')
                        
                        for item in data:
                            if item.get('startTime', '') <= now_str:
                                latest_day_ahead_price = item.get('price', 0)
                                break
                                
                        if latest_day_ahead_price == 0:
                            print("Day-Ahead: Found data but none with startTime <= now")
                    else:
                        print("Day-Ahead: Empty data array returned")
                else:
                    print(f"Day-Ahead API Error: HTTP {res.status_code} - {res.text[:200]}")
        except Exception as e:
            print(f"Day-ahead price error: {e}")

        # POWERWALL API
        pw_solar, pw_home, pw_battery, pw_grid, pw_level, pw_grid_status = 0, 0, 0, 0, 0, "UNKNOWN"
        try:
            if PW_IP and PW_PASSWORD:
                pw = pypowerwall.Powerwall(host=PW_IP, password=PW_PASSWORD, email=PW_EMAIL)
                pw_power = pw.power()
                if sum(pw_power.values()) != 0 or pw.level() > 0:
                    pw_solar, pw_home, pw_battery, pw_grid, pw_level, pw_grid_status = pw_power.get('solar', 0), pw_power.get('load', 0), pw_power.get('battery', 0), pw_power.get('site', 0), pw.level(), pw.grid_status()       
        except: pass

        # DATABASE INJECTION
        conn = sqlite3.connect('grid_data.db')
        cursor = conn.cursor()
        cursor.execute('''
            INSERT INTO energy_snapshots 
            (timestamp, carbon_intensity, demand_mw, total_generation_mw, net_flow_mw, wholesale_price, day_ahead_price, generation_mix, interconnector_flows, pw_solar_w, pw_home_w, pw_battery_w, pw_grid_w, pw_level, pw_grid_status, temp_c, wind_mph, daylight_secs, cloud_cover, oct_import_pence, oct_export_pence, oct_yest_import, oct_yest_export, oct_yest_gas, oct_yest_date)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        ''', (
            now_utc.strftime('%Y-%m-%dT%H:%M:%SZ'),
            carbon_intensity, true_demand, total_generation, total_net_flow, latest_price, latest_day_ahead_price,
            json.dumps(generation), json.dumps(interconnectors),
            pw_solar, pw_home, pw_battery, pw_grid, pw_level, pw_grid_status,
            temp_c, wind_mph, daylight_secs, cloud_cover, 
            oct_imp_pence, oct_exp_pence, oct_yest_imp, oct_yest_exp, oct_yest_gas, oct_final_date
        ))
        conn.commit()
        conn.close()
        print("-> Success! Row added to database.")

    except Exception as e: print(f"-> Harvester Error: {e}")

if __name__ == '__main__': fetch_and_store()