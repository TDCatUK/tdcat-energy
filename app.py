import os
import json
from flask import Flask, render_template, jsonify, request, send_from_directory
import sqlite3
from datetime import datetime

# Startup Flask
app = Flask(__name__)

# Google verification from static
@app.route('/googlef0e2d4f7f1f6e547.html') # Replace with your actual filename
def verify_google():
    return send_from_directory('static', 'googlef0e2d4f7f1f6e547.html')

@app.route('/sitemap.xml')
def sitemap():
    return send_from_directory('static', 'sitemap.xml')

@app.route('/robots.txt')
def robots():
    return send_from_directory('static', 'robots.txt')

CONFIG_FILE = 'config.json'

DEFAULT_CONFIG = {
    "theme": { "brand_cyan": "#30C5D5", "brand_orange": "#F6643C", "octo_pink": "#FF00A0", "tesla_green": "#00D241" },
    "octopus": { "color_imp": "#FF00A0", "color_exp": "#FF00A0" },
    "powerwall": { "solar_efficiency": 95.5 },
    "flow": { 
        "hv_gen": "#F6643C", "total": "#30C5D5", "storage": "#30C5D5", "demand": "#D4D4D8", "exports": "#FF00A0", 
        "bg_color": "#000000", "speed_mode": "relative", "base_speed": 5, "dot_size": 2.5,
        "icons": { "sol": "fa-solid fa-sun", "imp": "fa-solid fa-earth-europe", "hv": "fa-solid fa-industry", "wind": "fa-solid fa-wind", "psh": "fa-solid fa-battery-half", "dem": "fa-solid fa-house", "exp": "fa-solid fa-file-export" }
    },
    "map_nodes": {
        "uk": {"x": 460, "y": 460}, "ire": {"x": 280, "y": 460}, "fra": {"x": 510, "y": 680},
        "bel": {"x": 610, "y": 600}, "ned": {"x": 650, "y": 520}, "den": {"x": 800, "y": 380}, "nor": {"x": 680, "y": 200}
    },
    "fuels": { "wind": "#10B981", "lv_wind": "#5FB035", "solar": "#FFD700", "hydro": "#60A5FA", "pumped_storage": "#30C5D5", "biomass": "#8B4513", "nuclear": "#A1A1AA", "imports": "#64748B", "other": "#A855F7", "ocg": "#9A3412", "ccgt": "#F6643C" },
    "gradients": { "temp_hot": "#EF4444", "temp_cold": "#3B82F6" },
    "carbon": { "low": "#4ADE80", "med": "#F6643C", "high": "#EF4444" },
    "price": { "color_low": "#4ADE80", "color_med": "#F6643C", "color_high": "#EF4444", "thresh_low": 50, "thresh_high": 120 },
    "da_price": { "color_low": "#4ADE80", "color_med": "#10B981", "color_high": "#EF4444", "thresh_low": 50, "thresh_high": 120 },
    "mi_price": { "color_low": "#4ADE80", "color_med": "#3B82F6", "color_high": "#EF4444", "thresh_low": 50, "thresh_high": 120 },
    "demand": { "national": "#D4D4D8", "transmission": "#60A5FA", "net": "#FDBA74", "gross": "#EF4444", "dashed": "#FFFFFF" },
    "footer": { "use1_text": "Pexels Stock Photos", "use1_url": "#", "use2_text": "Rod Allsopp", "use2_url": "#", "use3_text": "OpenWRT", "use3_url": "#", "use4_text": "Love Your Libraries", "use4_url": "#", "fol1_text": "Twitter", "fol1_url": "#", "fol2_text": "Instagram", "fol2_url": "#", "fol3_text": "Patreon", "fol3_url": "#" }
}

def load_config():
    config = json.loads(json.dumps(DEFAULT_CONFIG)) 
    if os.path.exists(CONFIG_FILE):
        try:
            with open(CONFIG_FILE, 'r') as f:
                user_config = json.load(f)
                for key, val in user_config.items():
                    if isinstance(val, dict) and key in config:
                        config[key].update(val)
                    else:
                        config[key] = val
        except: pass
    return config

def save_config(config_data):
    with open(CONFIG_FILE, 'w') as f:
        json.dump(config_data, f, indent=4)

def get_db_connection():
    conn = sqlite3.connect('grid_data.db')
    conn.row_factory = sqlite3.Row
    return conn

@app.route('/')
def index(): return render_template('index.html')

@app.route('/admin')
def admin(): return render_template('admin.html')

@app.route('/about')
def about(): return render_template('about.html')

@app.route('/api/config', methods=['GET', 'POST'])
def handle_config():
    if request.method == 'POST':
        save_config(request.json)
        return jsonify({"status": "success"})
    return jsonify(load_config())

@app.route('/api/data')
def get_data():
    conn = get_db_connection()
    latest_row = conn.execute('SELECT * FROM energy_snapshots ORDER BY timestamp DESC LIMIT 1').fetchone()
    history_rows = conn.execute('SELECT * FROM energy_snapshots ORDER BY timestamp DESC LIMIT 288').fetchall()
    
    today_str = datetime.utcnow().strftime('%Y-%m-%d')
    today_rows = conn.execute('SELECT timestamp, pw_solar_w, pw_home_w, pw_battery_w, pw_grid_w FROM energy_snapshots WHERE timestamp LIKE ? ORDER BY timestamp ASC', (today_str + '%',)).fetchall()
        
    conn.close()

    if not latest_row: return jsonify({"error": "No data available"}), 404

    cum_solar = cum_home = cum_grid_import = cum_grid_export = cum_batt_dischg = cum_batt_chg = 0.0

    if len(today_rows) > 1:
        for i in range(1, len(today_rows)):
            t1 = datetime.strptime(today_rows[i-1]['timestamp'], '%Y-%m-%dT%H:%M:%SZ')
            t2 = datetime.strptime(today_rows[i]['timestamp'], '%Y-%m-%dT%H:%M:%SZ')
            dt_hours = (t2 - t1).total_seconds() / 3600.0
            if dt_hours > 1.0: dt_hours = 5.0 / 60.0

            w_solar = (today_rows[i-1]['pw_solar_w'] + today_rows[i]['pw_solar_w']) / 2.0
            cum_solar += (w_solar * dt_hours) / 1000.0
            
            w_home = (today_rows[i-1]['pw_home_w'] + today_rows[i]['pw_home_w']) / 2.0
            cum_home += (w_home * dt_hours) / 1000.0
            w_grid = (today_rows[i-1]['pw_grid_w'] + today_rows[i]['pw_grid_w']) / 2.0
            if w_grid > 0: cum_grid_import += (w_grid * dt_hours) / 1000.0
            else: cum_grid_export += (abs(w_grid) * dt_hours) / 1000.0
            w_batt = (today_rows[i-1]['pw_battery_w'] + today_rows[i]['pw_battery_w']) / 2.0
            if w_batt > 0: cum_batt_dischg += (w_batt * dt_hours) / 1000.0
            else: cum_batt_chg += (abs(w_batt) * dt_hours) / 1000.0

    latest = dict(latest_row)
    mix_col = 'generation_mix' if 'generation_mix' in latest else 'mix'
    ic_col = 'interconnector_flows' if 'interconnector_flows' in latest else 'interconnectors'
    
    raw_generation_mix = json.loads(latest[mix_col]) if latest[mix_col] else {}
    interconnector_flows = json.loads(latest[ic_col]) if latest[ic_col] else []

    clean_latest_mix = {}
    for label, mw in raw_generation_mix.items():
        if label == "Combined Cycle Gas (CCGT)": clean_latest_mix["CCGT"] = mw
        elif label == "Open Cycle Gas": clean_latest_mix["OCG"] = mw
        elif label in ["Coal", "OIL"]: 
            clean_latest_mix["Other"] = clean_latest_mix.get("Other", 0) + mw
        else: 
            clean_latest_mix[label] = clean_latest_mix.get(label, 0) + mw

    history_payload, carbon_history = [], []
    
    fuel_keys = { "Combined Cycle Gas (CCGT)": "ccgt", "CCGT": "ccgt", "Open Cycle Gas": "ocg", "OCG": "ocg", "Wind": "wind", "LV Wind": "lv_wind", "Solar": "solar", "Hydro": "hydro", "Pumped Storage": "pumped_storage", "Biomass": "biomass", "Nuclear": "nuclear", "Coal": "other", "OIL": "other", "Other": "other" }

    prev_gen, prev_demand = None, None

    for raw_row in reversed(history_rows):
        row = dict(raw_row)
        r_mix_col = 'generation_mix' if 'generation_mix' in row else 'mix'
        r_ic_col = 'interconnector_flows' if 'interconnector_flows' in row else 'interconnectors'
        mix = json.loads(row[r_mix_col]) if row[r_mix_col] else {}
        flows = json.loads(row[r_ic_col]) if row[r_ic_col] else []
        
        total_gen = sum(mix.values())
        total_imports = sum(f['flow'] for f in flows if f['flow'] > 0)
        grand_total = total_gen + total_imports
        
        clean_gen = row['total_generation_mw'] or 0
        clean_demand = row['demand_mw'] or 0
        if clean_gen < 1000 and prev_gen: clean_gen = prev_gen
        if clean_demand < 1000 and prev_demand: clean_demand = prev_demand
        prev_gen, prev_demand = clean_gen, clean_demand

        exports_mw = sum(abs(f['flow']) for f in flows if f['flow'] < 0)
        psh_mw = mix.get('Pumped Storage', 0)
        psh_pumping_mw = abs(psh_mw) if psh_mw < 0 else 0
        solar_mw = mix.get('Solar', 0)

        mix_array = []
        if grand_total > 0:
            for label, mw in mix.items():
                simple_key = fuel_keys.get(label, "other")
                existing = next((item for item in mix_array if item["fuel"] == simple_key), None)
                if existing: existing["perc"] += (mw / grand_total) * 100
                else: mix_array.append({"fuel": simple_key, "perc": (mw / grand_total) * 100})
            if total_imports > 0: mix_array.append({"fuel": "imports", "perc": (total_imports / grand_total) * 100})

        history_payload.append({
            "time": row['timestamp'], 
            "demand_mw": clean_demand, 
            "total_generation_mw": clean_gen,
            "net_flow_mw": row['net_flow_mw'] or 0, 
            "wholesale_price": row['wholesale_price'] or 0, 
            "day_ahead_price": row['day_ahead_price'] or 0,
            "market_index_price": row.get('market_index_price', 0) or 0,
            "grid_frequency": row.get('grid_frequency', 50.0) or 50.0,
            "net_imbalance_volume": row.get('net_imbalance_volume', 0) or 0,
            "mix": mix_array,
            "pw_solar_w": row['pw_solar_w'] or 0, 
            "pw_home_w": row['pw_home_w'] or 0,
            "pw_grid_w": row['pw_grid_w'] or 0, 
            "pw_battery_w": row['pw_battery_w'] or 0, 
            "pw_level": row['pw_level'] or 0,
            "oct_import_pence": row['oct_import_pence'] or 0, 
            "oct_export_pence": row['oct_export_pence'] or 0,
            "exports_mw": exports_mw, 
            "psh_pumping_mw": psh_pumping_mw, 
            "solar_mw": solar_mw
        })
        carbon_history.append({"time": row['timestamp'], "intensity": row['carbon_intensity'] or 0})

    l_exports_mw = sum(abs(f['flow']) for f in interconnector_flows if f['flow'] < 0)
    l_psh_mw = raw_generation_mix.get('Pumped Storage', 0)
    l_psh_pumping_mw = abs(l_psh_mw) if l_psh_mw < 0 else 0
    l_solar_mw = raw_generation_mix.get('Solar', 0)

    yest_gas_m3 = latest.get('oct_yest_gas', 0)

    weather_status = 'UP'
    try:
        mtime = os.path.getmtime('static/forecast.json')
        if (datetime.now().timestamp() - mtime) > 1200:
            weather_status = 'DOWN'
    except:
        weather_status = 'DOWN'


    response_data = {
        "demand_mw": latest['demand_mw'] or 0, 
        "total_generation_mw": latest['total_generation_mw'] or 0,
        "net_flow_mw": latest['net_flow_mw'] or 0, 
        "wholesale_price": latest['wholesale_price'] or 0,
        "day_ahead_price": latest['day_ahead_price'] or 0,
        "market_index_price": latest.get('market_index_price', 0) or 0,
        "grid_frequency": latest.get('grid_frequency', 50.0) or 50.0,
        "net_imbalance_volume": latest.get('net_imbalance_volume', 0) or 0,
        "carbon_intensity": latest['carbon_intensity'] or 0, 
        "generation_mix": clean_latest_mix,
        "interconnector_flows": interconnector_flows,
        "breakdown": {
            "transmission_mw": latest['demand_mw'] or 0, 
            "embedded_mw": l_solar_mw + (latest.get('embedded_wind_mw', 0) or 0),
            "exports_mw": l_exports_mw,
            "psh_pumping_mw": l_psh_pumping_mw, 
            "station_load_mw": 500
        },

        "powerwall": {
            "solar_w": latest['pw_solar_w'] or 0, 
            "home_w": latest['pw_home_w'] or 0,
            "grid_w": latest['pw_grid_w'] or 0, 
            "battery_w": latest['pw_battery_w'] or 0, 
            "level": latest['pw_level'] or 0, 
            "grid_status": latest['pw_grid_status'] or 'UP',
            "cum_solar_kwh": cum_solar, 
            "cum_home_kwh": cum_home,
            "cum_grid_import_kwh": cum_grid_import, 
            "cum_grid_export_kwh": cum_grid_export,
            "cum_batt_dischg_kwh": cum_batt_dischg, 
            "cum_batt_chg_kwh": cum_batt_chg
        },
        "weather": {
            "status": weather_status,
            "temp_c": latest['temp_c'] or 0, 
            "wind_mph": latest['wind_mph'] or 0,
            "daylight_secs": latest['daylight_secs'] or 0, 
            "cloud_cover": latest['cloud_cover'] or 0
        },
        "octopus": {
            "import_pence": latest['oct_import_pence'] or 0, 
            "export_pence": latest['oct_export_pence'] or 0,
            "yest_import_kwh": latest['oct_yest_import'] or 0, 
            "yest_export_kwh": latest['oct_yest_export'] or 0,
            "yest_gas_m3": yest_gas_m3, 
            "yest_gas_kwh": yest_gas_m3 * 11.222, 
            "yest_date": latest['oct_yest_date'] or ''
        },
        "cloudflare": {
            "visits": latest.get('cf_visits_24h', 0),
            "requests": latest.get('cf_requests_24h', 0),
            "bytes": latest.get('cf_bytes_24h', 0)
        },
        "history": history_payload, 
        "carbon_history": carbon_history
    }
    return jsonify(response_data)

if __name__ == '__main__': 
    app.run(host='0.0.0.0', port=5000, debug=False)