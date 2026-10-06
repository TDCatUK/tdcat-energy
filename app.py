import os
import json
from flask import Flask, render_template, jsonify, request, send_from_directory
import sqlite3
from datetime import date, datetime, timezone
from zoneinfo import ZoneInfo

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
        "icons": { "sol": "fa-solid fa-sun", "imp": "fa-solid fa-earth-europe", "hv": "fa-solid fa-industry", "wind": "fa-solid fa-wind", "psh": "fa-solid fa-water", "batt": "fa-solid fa-battery-half", "dem": "fa-solid fa-house", "exp": "fa-solid fa-file-export" }
    },
    "map_nodes": {
        "uk": {"x": 460, "y": 460}, "ire": {"x": 280, "y": 460}, "fra": {"x": 510, "y": 680},
        "bel": {"x": 610, "y": 600}, "ned": {"x": 650, "y": 520}, "den": {"x": 800, "y": 380}, "nor": {"x": 680, "y": 200}
    },
    "fuels": { "wind": "#10B981", "lv_wind": "#5FB035", "solar": "#FFD700", "hydro": "#60A5FA", "pumped_storage": "#30C5D5", "biomass": "#8B4513", "nuclear": "#A1A1AA", "imports": "#64748B", "other": "#A855F7", "ocg": "#9A3412", "ccgt": "#F6643C", "battery": "#A78BFA" },
    "gradients": { "temp_hot": "#EF4444", "temp_cold": "#3B82F6" },
    "carbon": { "low": "#4ADE80", "med": "#F6643C", "high": "#EF4444" },
    "price": { "color_low": "#4ADE80", "color_med": "#F6643C", "color_high": "#EF4444", "thresh_low": 50, "thresh_high": 120 },
    "da_price": { "color_low": "#4ADE80", "color_med": "#10B981", "color_high": "#EF4444", "thresh_low": 50, "thresh_high": 120 },
    "mi_price": { "color_low": "#4ADE80", "color_med": "#3B82F6", "color_high": "#EF4444", "thresh_low": 50, "thresh_high": 120 },
    "demand": { "national": "#D4D4D8", "transmission": "#60A5FA", "net": "#FDBA74", "gross": "#EF4444", "dashed": "#FFFFFF" },
    "gas": {
        "supply_north_sea": "#30C5D5", "supply_norway": "#60A5FA", "supply_lng": "#F050F8", "supply_storage": "#00D241", "supply_continent": "#A1A1AA",
        "demand_homes": "#D4D4D8", "demand_power": "#F6643C", "demand_industry": "#A1A1AA", "demand_exports": "#FF00A0", "demand_storage": "#00D241",
        "line_supply": "#30C5D5", "line_demand": "#F6643C", "line_linepack": "#D4D4D8",
        "storage_low": "#EF4444", "storage_med": "#F6643C", "storage_high": "#4ADE80", "storage_thresh_low": 75, "storage_thresh_high": 100
    },
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
    # Write to a temporary file and swap it in, so a failed write can't leave a half-written config
    tmp = CONFIG_FILE + '.tmp'
    with open(tmp, 'w') as f:
        json.dump(config_data, f, indent=4)
    os.replace(tmp, CONFIG_FILE)

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

@app.route('/changelog')
def changelog(): return render_template('changelog.html')

@app.route('/api/config')
def get_config():
    return jsonify(load_config())

# Saving lives under /admin/ so the Cloudflare Access login that protects /admin/* covers it.
# /api/config stays public and read-only because the dashboard needs it.
@app.route('/admin/api/config', methods=['POST'])
def update_config():
    config_data = request.get_json(silent=True)
    if not isinstance(config_data, dict) or not all(isinstance(v, dict) for v in config_data.values()):
        return jsonify({"status": "error", "message": "Expected the config as a JSON object of sections"}), 400
    save_config(config_data)
    return jsonify({"status": "success"})

LONDON = ZoneInfo('Europe/London')

# Older rows stored some interconnectors under their raw Elexon code
INTERCONNECTOR_NAMES = { "INTGRNL": "Ireland (Greenlink)" }

FUEL_KEYS = { "Combined Cycle Gas (CCGT)": "ccgt", "CCGT": "ccgt", "Open Cycle Gas": "ocg", "OCG": "ocg", "Wind": "wind", "LV Wind": "lv_wind", "Solar": "solar", "Hydro": "hydro", "Pumped Storage": "pumped_storage", "Biomass": "biomass", "Nuclear": "nuclear", "Coal": "other", "OIL": "other", "Other": "other" }

def load_flows(raw):
    flows = json.loads(raw) if raw else []
    for f in flows:
        f['name'] = INTERCONNECTOR_NAMES.get(f['name'], f['name'])
    return flows

def summarise_row(row):
    """Generation, interconnector and demand figures for one stored snapshot.

    Pumped storage is negative while pumping. That is demand, not generation,
    so it is clamped out of generation and reported as psh_pumping_mw.
    """
    mix = json.loads(row['generation_mix']) if row['generation_mix'] else {}
    flows = load_flows(row['interconnector_flows'])
    gen = {label: max(0, mw or 0) for label, mw in mix.items()}
    total_gen = sum(gen.values())
    imports = sum(f['flow'] for f in flows if f['flow'] > 0)
    exports = sum(-f['flow'] for f in flows if f['flow'] < 0)
    # Solar and LV Wind are embedded (distribution-connected) generation
    embedded = gen.get('Solar', 0) + gen.get('LV Wind', 0)
    return {
        "gen": gen, "flows": flows,
        "total_gen_mw": total_gen, "imports_mw": imports, "exports_mw": exports,
        "net_flow_mw": imports - exports, "supply_mw": total_gen + imports,
        "psh_pumping_mw": max(0, -(mix.get('Pumped Storage', 0) or 0)),
        "solar_mw": gen.get('Solar', 0), "embedded_mw": embedded,
    }

# Typical calorific value of NTS gas, used to turn gas flow into energy
GAS_CV_MJ_PER_M3 = 39.5

def storage_rows(conn):
    """Daily storage rows with National Gas's one-off glitches removed.

    The published series has odd days with zeros, or stock and capacity far off their neighbours.
    GB storage can't move more than about 1-2 TWh a day, so a day more than 1.5 TWh (stock) or
    10% (capacity) from the median of the surrounding week is treated as a data error and skipped.
    """
    try:
        rows = [dict(r) for r in conn.execute('SELECT * FROM gas_storage_daily WHERE storage_stock_gwh IS NOT NULL AND storage_space_gwh IS NOT NULL ORDER BY gas_day')]
    except sqlite3.OperationalError:
        return []  # the harvester creates gas_storage_daily on its first gas reading
    stock = [r['storage_stock_gwh'] for r in rows]
    capacity = [r['storage_stock_gwh'] + r['storage_space_gwh'] for r in rows]
    def median_around(values, i):
        window = sorted(values[max(0, i - 3): i + 4])
        return window[len(window) // 2]
    return [r for i, r in enumerate(rows)
            if stock[i] > 0 and abs(stock[i] - median_around(stock, i)) <= 1500
            and abs(capacity[i] - median_around(capacity, i)) <= 0.1 * median_around(capacity, i)]

def get_gas_storage(conn):
    """Latest daily gas storage stock, compared with the same date in up to five previous years."""
    rows = storage_rows(conn)
    if not rows: return None
    stock_by_day = {r['gas_day']: r['storage_stock_gwh'] for r in rows}
    latest = dict(rows[-1])
    day = date.fromisoformat(latest['gas_day'])
    previous = []
    for years_back in range(1, 6):
        try: same_day = day.replace(year=day.year - years_back)
        except ValueError: same_day = day.replace(year=day.year - years_back, day=28)  # 29 February
        if same_day.isoformat() in stock_by_day:
            previous.append({"year": same_day.year, "stock_gwh": stock_by_day[same_day.isoformat()]})
    total = lambda stock, space: stock + space if stock is not None and space is not None else None
    return {
        "gas_day": latest['gas_day'],
        "stock_gwh": latest['storage_stock_gwh'],
        "capacity_gwh": total(latest['storage_stock_gwh'], latest['storage_space_gwh']),
        "rough_stock_gwh": latest['rough_stock_gwh'],
        "rough_capacity_gwh": total(latest['rough_stock_gwh'], latest['rough_space_gwh']),
        "lng_stock_gwh": latest['lng_stock_gwh'],
        "lng_capacity_gwh": total(latest['lng_stock_gwh'], latest['lng_space_gwh']),
        "previous": previous,
        "average_gwh": sum(p['stock_gwh'] for p in previous) / len(previous) if previous else None,
        "lowest_on_record": bool(previous) and latest['storage_stock_gwh'] < min(p['stock_gwh'] for p in previous),
    }

@app.route('/api/gas/storage')
def gas_storage_history():
    """Daily storage stock (GWh) for every gas day on record, for the storage charts."""
    conn = get_db_connection()
    rows = storage_rows(conn)
    conn.close()
    return jsonify({"days": [r['gas_day'] for r in rows], "stock_gwh": [r['storage_stock_gwh'] for r in rows]})

def get_gas(conn, gas_fired_mw):
    """Latest National Gas figures plus 24 h of history, or None before the harvester's first gas reading."""
    try:
        rows = conn.execute('SELECT * FROM gas_snapshots ORDER BY timestamp DESC LIMIT 288').fetchall()
    except sqlite3.OperationalError:
        return None  # the harvester creates gas_snapshots on its first gas reading
    if not rows: return None
    latest = dict(rows[0])
    demand = json.loads(latest['demand_json'] or '{}')
    # mcm/d of gas -> GW of fuel energy burned
    power_thermal_gw = demand.get('Power stations', 0) * GAS_CV_MJ_PER_M3 * 1000 / 86400
    return {
        "updated": latest['timestamp'],
        "flows_time": latest['flows_time'],
        "linepack_mcm": latest['linepack_mcm'],
        "supply_mcmd": latest['supply_mcmd'],
        "demand_mcmd": latest['demand_mcmd'],
        "supply": json.loads(latest['supply_json'] or '{}'),
        "demand": demand,
        "storage": get_gas_storage(conn),
        "power_thermal_gw": power_thermal_gw,
        "power_electric_gw": gas_fired_mw / 1000,
        "history": [{"time": r['timestamp'], "linepack_mcm": r['linepack_mcm'], "supply_mcmd": r['supply_mcmd'], "demand_mcmd": r['demand_mcmd']} for r in reversed(rows)]
    }

@app.route('/api/data')
def get_data():
    conn = get_db_connection()
    history_rows = conn.execute('SELECT * FROM energy_snapshots ORDER BY timestamp DESC LIMIT 288').fetchall()

    # "Today" is the UK day: during BST it starts at 23:00 UTC the previous day
    uk_midnight = datetime.now(LONDON).replace(hour=0, minute=0, second=0, microsecond=0)
    day_start = uk_midnight.astimezone(timezone.utc).strftime('%Y-%m-%dT%H:%M:%SZ')
    today_rows = conn.execute('SELECT timestamp, pw_solar_w, pw_home_w, pw_battery_w, pw_grid_w FROM energy_snapshots WHERE timestamp >= ? ORDER BY timestamp ASC', (day_start,)).fetchall()
    latest_mix = json.loads(history_rows[0]['generation_mix'] or '{}') if history_rows else {}
    gas = get_gas(conn, sum(max(0, latest_mix.get(k, 0) or 0) for k in ("Combined Cycle Gas (CCGT)", "Open Cycle Gas")))

    conn.close()

    if not history_rows: return jsonify({"error": "No data available"}), 404

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

    latest = dict(history_rows[0])
    history_payload, carbon_history = [], []
    prev = None

    for raw_row in reversed(history_rows):
        row = dict(raw_row)
        s = summarise_row(row)

        # An Elexon timeout leaves a row with only Solar/LV Wind in the mix: reuse the last good supply picture
        if prev and s['total_gen_mw'] - s['embedded_mw'] < 1000:
            s = dict(prev)
        # demand_mw is stored as ITSDO + embedded solar + LV wind, so take the embedded part back off
        s['transmission_mw'] = (row['demand_mw'] or 0) - s['embedded_mw']
        if prev and s['transmission_mw'] < 1000: s['transmission_mw'] = prev['transmission_mw']
        prev = s

        by_fuel = {}
        for label, mw in s['gen'].items():
            key = FUEL_KEYS.get(label, "other")
            by_fuel[key] = by_fuel.get(key, 0) + mw
        if s['imports_mw'] > 0: by_fuel["imports"] = s['imports_mw']
        mix_array = []
        if s['supply_mw'] > 0:
            mix_array = [{"fuel": fuel, "mw": mw, "perc": (mw / s['supply_mw']) * 100} for fuel, mw in by_fuel.items()]

        history_payload.append({
            "time": row['timestamp'],
            "demand_mw": s['transmission_mw'] + s['embedded_mw'],
            "transmission_mw": s['transmission_mw'],
            "embedded_mw": s['embedded_mw'],
            "total_generation_mw": s['total_gen_mw'],
            "supply_mw": s['supply_mw'],
            "net_flow_mw": s['net_flow_mw'],
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
            "exports_mw": s['exports_mw'],
            "psh_pumping_mw": s['psh_pumping_mw'],
            "solar_mw": s['solar_mw'],
            "bess_discharge_mw": row.get('bess_discharge_mw'),
            "bess_charge_mw": row.get('bess_charge_mw')
        })
        carbon_history.append({"time": row['timestamp'], "intensity": row['carbon_intensity'] or 0})

    latest_s = prev
    clean_latest_mix = {}
    for label, mw in latest_s['gen'].items():
        if label == "Combined Cycle Gas (CCGT)": name = "CCGT"
        elif label == "Open Cycle Gas": name = "OCG"
        elif label in ["Coal", "OIL"]: name = "Other"
        else: name = label
        clean_latest_mix[name] = clean_latest_mix.get(name, 0) + mw

    yest_gas_m3 = latest.get('oct_yest_gas', 0)

    weather_status = 'UP'
    try:
        mtime = os.path.getmtime('static/forecast.json')
        if (datetime.now().timestamp() - mtime) > 1200:
            weather_status = 'DOWN'
    except:
        weather_status = 'DOWN'


    response_data = {
        "demand_mw": latest_s['transmission_mw'] + latest_s['embedded_mw'],
        "total_generation_mw": latest_s['total_gen_mw'],
        "net_flow_mw": latest_s['net_flow_mw'],
        "wholesale_price": latest['wholesale_price'] or 0,
        "day_ahead_price": latest['day_ahead_price'] or 0,
        "market_index_price": latest.get('market_index_price', 0) or 0,
        "grid_frequency": latest.get('grid_frequency', 50.0) or 50.0,
        "net_imbalance_volume": latest.get('net_imbalance_volume', 0) or 0,
        "carbon_intensity": latest['carbon_intensity'] or 0,
        "generation_mix": clean_latest_mix,
        "interconnector_flows": latest_s['flows'],
        "breakdown": {
            "transmission_mw": latest_s['transmission_mw'],
            "embedded_mw": latest_s['embedded_mw'],
            "exports_mw": latest_s['exports_mw'],
            "psh_pumping_mw": latest_s['psh_pumping_mw'],
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
        "battery": {
            "discharge_mw": latest.get('bess_discharge_mw'),
            "charge_mw": latest.get('bess_charge_mw')
        },
        "cloudflare": {
            "visits": latest.get('cf_visits_24h', 0),
            "requests": latest.get('cf_requests_24h', 0),
            "bytes": latest.get('cf_bytes_24h', 0)
        },
        "gas": gas,
        "history": history_payload,
        "carbon_history": carbon_history
    }
    return jsonify(response_data)

if __name__ == '__main__': 
    app.run(host='0.0.0.0', port=5000, debug=False)