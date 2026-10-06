import os
import json
import threading
from flask import Flask, render_template, jsonify, request, send_from_directory
import sqlite3
from datetime import date, datetime, timedelta, timezone
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
    "patterns": { "offpeak_start": "23:30", "offpeak_end": "05:30" },
    "frequency": { "color_target": "#30C5D5", "color_limit": "#F6643C", "thresh_low": 49.8, "thresh_high": 50.2 },
    "gas": {
        "supply_north_sea": "#30C5D5", "supply_norway": "#60A5FA", "supply_lng": "#F050F8", "supply_storage": "#00D241", "supply_continent": "#A1A1AA",
        "demand_homes": "#D4D4D8", "demand_power": "#F6643C", "demand_industry": "#A1A1AA", "demand_exports": "#FF00A0", "demand_storage": "#00D241",
        "line_supply": "#30C5D5", "line_demand": "#F6643C", "line_linepack": "#D4D4D8", "accent": "#3B82F6",
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

# GB has never needed more than about 60 GW. A few stored rows add up to 300+ GW (Elexon glitches), so they're skipped.
MAX_PLAUSIBLE_GEN_MW = 65000

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

def table_rows(conn, sql, params=()):
    """Rows from one of the tables the harvester creates itself, or [] before it has created it."""
    try:
        return conn.execute(sql, params).fetchall()
    except sqlite3.OperationalError:
        return []

@app.route('/api/demand/recent')
def demand_recent():
    """National demand and rooftop solar for each half-hour of the last 31 days, stamped with the UK local start time."""
    conn = get_db_connection()
    rows = table_rows(conn, "SELECT * FROM neso_demand_hh WHERE settlement_date >= date('now', '-32 days') ORDER BY settlement_date, settlement_period")
    conn.close()
    out = []
    for r in rows:
        # Settlement periods count half-hours from UK midnight, so clock-change days have 46 or 50 of them
        midnight = datetime.combine(date.fromisoformat(r['settlement_date']), datetime.min.time(), LONDON).astimezone(timezone.utc)
        start = (midnight + timedelta(minutes=30 * (r['settlement_period'] - 1))).astimezone(LONDON)
        out.append({"t": start.strftime('%Y-%m-%d %H:%M'), "nd": r['nd'], "solar": r['embedded_solar']})
    return jsonify({"rows": out})

@app.route('/api/demand/duck')
def demand_duck():
    """Average national demand and rooftop solar through the day for one month, every year on record, plus solar records."""
    month = request.args.get('month', type=int) or datetime.now(LONDON).month
    conn = get_db_connection()
    profiles = table_rows(conn, "SELECT * FROM duck_profiles WHERE month = ? ORDER BY year, settlement_period", (month,))
    records = table_rows(conn, "SELECT * FROM duck_records ORDER BY year")
    conn.close()
    years = {}
    for r in profiles:
        y = years.setdefault(str(r['year']), {"nd": [None] * 48, "solar": [None] * 48, "days": 0})
        y["nd"][r['settlement_period'] - 1] = r['nd']
        y["solar"][r['settlement_period'] - 1] = r['embedded_solar']
        y["days"] = max(y["days"], r['days'])
    return jsonify({"month": month, "years": years, "records": [dict(r) for r in records]})

@app.route('/api/forecast')
def forecast():
    """Agile import/export rates (p/kWh) and the national carbon intensity forecast, from the current half-hour on."""
    now = datetime.now(timezone.utc)
    start = now.replace(minute=now.minute // 30 * 30, second=0, microsecond=0).strftime('%Y-%m-%dT%H:%M:%SZ')
    conn = get_db_connection()
    agile = table_rows(conn, 'SELECT valid_from, import_p, export_p FROM agile_rates WHERE valid_from >= ? ORDER BY valid_from', (start,))
    carbon = table_rows(conn, 'SELECT period_from, forecast, index_label FROM carbon_forecast WHERE period_from >= ? ORDER BY period_from', (start,))
    conn.close()
    return jsonify({
        "from": start,
        "agile": [{"t": r['valid_from'], "import": r['import_p'], "export": r['export_p']} for r in agile],
        "carbon": [{"t": r['period_from'], "forecast": r['forecast'], "index": r['index_label']} for r in carbon if r['forecast'] is not None],
    })

@app.route('/api/frequency')
def frequency():
    """Every 15-second frequency reading for the last `hours` (up to 24), plus today's low, high and time outside the limits."""
    hours = min(max(request.args.get('hours', 1, type=float), 0.25), 24)
    limits = load_config()['frequency']
    low, high = float(limits['thresh_low']), float(limits['thresh_high'])
    conn = get_db_connection()
    try:
        latest = conn.execute('SELECT MAX(t) FROM frequency_readings').fetchone()[0]
    except sqlite3.OperationalError:
        latest = None  # the harvester creates the table on its first run
    if latest is None:
        conn.close()
        return jsonify({"readings": [], "today": None})
    readings = conn.execute('SELECT t, hz FROM frequency_readings WHERE t > ? ORDER BY t', (latest - hours * 3600,)).fetchall()
    # Today is the UK day
    since = int(datetime.now(LONDON).replace(hour=0, minute=0, second=0, microsecond=0).timestamp())
    count, lowest, highest, outside, outside_statutory = conn.execute(
        'SELECT COUNT(*), MIN(hz), MAX(hz), SUM(hz < ? OR hz > ?), SUM(hz < 49.5 OR hz > 50.5) FROM frequency_readings WHERE t >= ?',
        (low, high, since)).fetchone()
    today = None
    if count:
        lowest_t = conn.execute('SELECT t FROM frequency_readings WHERE t >= ? AND hz = ? ORDER BY t LIMIT 1', (since, lowest)).fetchone()[0]
        highest_t = conn.execute('SELECT t FROM frequency_readings WHERE t >= ? AND hz = ? ORDER BY t LIMIT 1', (since, highest)).fetchone()[0]
        # Each reading stands for 15 seconds
        today = {"readings": count, "min": lowest, "min_t": lowest_t, "max": highest, "max_t": highest_t,
                 "outside_secs": outside * 15, "outside_pct": outside / count * 100, "outside_statutory_secs": outside_statutory * 15}
    conn.close()
    return jsonify({"readings": [[t, hz] for t, hz in readings], "latest": latest, "low": low, "high": high, "today": today})

# === DATA-SOURCE HEALTH (the /status page) ===
# The source list and the ok/warn/fail rules live in sources.py, which the harvester's alerts use too
from sources import SOURCES, parse_utc, source_state

HARVESTER_LATE_MIN = 15  # the harvester runs every 5 minutes

@app.route('/status')
def status_page(): return render_template('status.html')

@app.route('/api/status')
def status():
    """Each data source's state, last good fetch and recent record. ?summary=1 skips the per-hour history."""
    now = datetime.now(timezone.utc)
    summary = request.args.get('summary') == '1'
    conn = get_db_connection()
    latest = {r['source']: dict(r) for r in table_rows(conn, 'SELECT * FROM source_status')}
    days = 1 if summary else 7
    runs = table_rows(conn, 'SELECT * FROM source_runs WHERE timestamp >= ? ORDER BY timestamp',
                      ((now - timedelta(days=days)).strftime('%Y-%m-%dT%H:%M:%SZ'),))
    last_snapshot = conn.execute('SELECT MAX(timestamp) FROM energy_snapshots').fetchone()[0]
    conn.close()

    # Hourly cells for the last 7 days: [runs that tried the source, runs where it failed]
    first_hour = now.replace(minute=0, second=0, microsecond=0) - timedelta(hours=167)
    cells, totals = {}, {}
    for run in runs:
        t = parse_utc(run['timestamp'])
        hour = int((t - first_hour).total_seconds() // 3600)
        recent = now - t <= timedelta(days=1)
        for key, failed in [(k, False) for k in (run['ok'] or '').split(',') if k] + [(k, True) for k in (run['failed'] or '').split(',') if k]:
            if not summary and 0 <= hour < 168:
                cell = cells.setdefault(key, [[0, 0] for _ in range(168)])[hour]
                cell[0] += 1; cell[1] += failed
            for span in ('7d', '24h') if recent else ('7d',):
                tally = totals.setdefault((key, span), [0, 0])
                tally[0] += 1; tally[1] += failed

    groups, states = [], []
    for group, sources in SOURCES:
        items = []
        for key, name, description, every in sources:
            row = latest.get(key)
            state = source_state(row, every, now)
            states.append(state)
            uptime = {span: (100 * (1 - totals[(key, span)][1] / totals[(key, span)][0]) if (key, span) in totals else None) for span in ('24h', '7d')}
            item = {"key": key, "name": name, "description": description, "every_min": every, "state": state, "uptime": uptime,
                    **({k: row[k] for k in ('last_ok', 'last_attempt', 'last_error', 'last_error_at', 'data_time', 'fails')} if row else {})}
            if not summary:
                item["hours"] = [None if not a else round(1 - f / a, 2) for a, f in cells.get(key, [[0, 0]] * 168)]
            items.append(item)
        groups.append({"name": group, "sources": items})

    last_run = runs[-1] if runs else None
    last_time = last_run['timestamp'] if last_run else last_snapshot
    harvester_late = not last_time or (now - parse_utc(last_time)).total_seconds() > HARVESTER_LATE_MIN * 60
    overall = 'fail' if harvester_late or 'fail' in states else 'warn' if 'warn' in states else 'ok'
    runs_24h = [r for r in runs if now - parse_utc(r['timestamp']) <= timedelta(days=1)]
    return jsonify({
        "now": now.strftime('%Y-%m-%dT%H:%M:%SZ'),
        "overall": overall,
        "counts": {s: states.count(s) for s in ('ok', 'warn', 'fail', 'unknown')},
        "harvester": {
            "last_run": last_time, "late": harvester_late,
            "seconds": last_run['seconds'] if last_run else None,
            "runs_24h": len(runs_24h),
            "avg_seconds_24h": sum(r['seconds'] or 0 for r in runs_24h) / len(runs_24h) if runs_24h else None,
        },
        "first_hour": first_hour.strftime('%Y-%m-%dT%H:%M:%SZ'),
        "groups": groups,
    })

# === LONGER HISTORY (the /history page) ===
# Every stored 5-minute row is folded into hourly sums once, then topped up as new rows arrive. Flask keeps
# them in memory, so a restart rebuilds them (about a second). Days are combined from hours, and each row
# goes through summarise_row(), so the history uses the same maths as the live charts.
HISTORY_COLUMNS = ('timestamp, generation_mix, interconnector_flows, demand_mw, carbon_intensity, market_index_price, wholesale_price, '
                   'oct_import_pence, oct_export_pence, pw_solar_w, pw_home_w, pw_grid_w, pw_battery_w, pw_level, temp_c, bess_discharge_mw, bess_charge_mw')
MIX_KEYS = sorted(set(FUEL_KEYS.values()) | {"imports"})
history_lock = threading.Lock()
history_hours = {}   # UTC hour start (unix seconds) -> {"sum": {}, "n": {}, "max": {}, "min": {}}
history_upto = None  # start of the newest hour folded in; refolded on the next refresh as it fills up
freq_hours = {}      # UTC hour start -> (lowest Hz, highest Hz, readings, readings outside the limits)
freq_state = {"limits": None, "earliest": None, "upto": None}

def fold_row(row):
    """Add one snapshot to its hour. Failed fetches were stored as 0, so zeros are skipped where 0 isn't a real value."""
    t = int(parse_utc(row['timestamp']).timestamp())
    h = history_hours.setdefault(t // 3600 * 3600, {"sum": {}, "n": {}, "max": {}, "min": {}})
    def add(key, value):
        h["sum"][key] = h["sum"].get(key, 0) + value
        h["n"][key] = h["n"].get(key, 0) + 1
    def extreme(key, value):
        if key not in h["max"] or value > h["max"][key][0]: h["max"][key] = (value, t)
        if key not in h["min"] or value < h["min"][key][0]: h["min"][key] = (value, t)

    s = summarise_row(row)
    if s['total_gen_mw'] - s['embedded_mw'] >= 1000 and s['total_gen_mw'] <= MAX_PLAUSIBLE_GEN_MW:  # a row where a sane Elexon mix arrived
        by_fuel = {}
        for label, mw in s['gen'].items():
            by_fuel[FUEL_KEYS.get(label, "other")] = by_fuel.get(FUEL_KEYS.get(label, "other"), 0) + mw
        by_fuel["imports"] = s['imports_mw']
        for key in MIX_KEYS:
            add("mix:" + key, by_fuel.get(key, 0))
        add("net_flow", s['net_flow_mw'])
        extreme("wind", by_fuel.get("wind", 0) + by_fuel.get("lv_wind", 0))
        extreme("solar", by_fuel.get("solar", 0))
        transmission = (row['demand_mw'] or 0) - s['embedded_mw']
        if transmission >= 1000:
            add("demand", transmission + s['embedded_mw'])
            extreme("demand", transmission + s['embedded_mw'])
    if row['bess_discharge_mw'] is not None:
        add("mix:battery", row['bess_discharge_mw'])
    if row['carbon_intensity']:
        add("carbon", row['carbon_intensity'])
    if row['market_index_price']:
        add("mip", row['market_index_price'])
        extreme("mip", row['market_index_price'])
    if row['wholesale_price']:
        add("ssp", row['wholesale_price'])
    if row['oct_import_pence'] or row['oct_export_pence']:
        add("agile_import", row['oct_import_pence'] or 0)
        add("agile_export", row['oct_export_pence'] or 0)
    pw = [row['pw_solar_w'] or 0, row['pw_home_w'] or 0, row['pw_grid_w'] or 0, row['pw_battery_w'] or 0]
    if any(pw) or (row['pw_level'] or 0) > 0:  # all zeros means the Powerwall wasn't reachable
        solar, home, grid, battery = pw
        for key, watts in (("pw_solar", max(0, solar)), ("pw_home", home), ("pw_import", max(0, grid)), ("pw_export", max(0, -grid)),
                           ("pw_batt_out", max(0, battery)), ("pw_batt_in", max(0, -battery))):
            add(key, watts)
    if row['temp_c'] is not None:
        add("temp", row['temp_c'])

def refresh_history(conn):
    """Fold in rows since the last refresh, redoing the newest hour."""
    global history_upto
    if history_upto:
        cutoff = int(parse_utc(history_upto).timestamp())
        for hour in [k for k in history_hours if k >= cutoff]: del history_hours[hour]
    rows = conn.execute(f'SELECT {HISTORY_COLUMNS} FROM energy_snapshots WHERE timestamp >= ? ORDER BY timestamp', (history_upto or '',)).fetchall()
    for row in rows: fold_row(row)
    if rows:
        history_upto = parse_utc(rows[-1]['timestamp']).replace(minute=0, second=0).strftime('%Y-%m-%dT%H:%M:%SZ')

def refresh_frequency(conn, low, high):
    """Hourly low, high and time outside the limits from the 15-second readings. Rebuilt if the limits
    change or older readings appear (the harvester back-fills history a week at a time)."""
    try:
        earliest = conn.execute('SELECT MIN(t) FROM frequency_readings').fetchone()[0]
    except sqlite3.OperationalError:
        return  # the harvester creates the table on its first run
    if freq_state["limits"] != (low, high) or (earliest is not None and freq_state["earliest"] is not None and earliest < freq_state["earliest"]):
        freq_hours.clear()
        freq_state.update(limits=(low, high), upto=None)
    freq_state["earliest"] = earliest
    for hour, lowest, highest, count, outside in conn.execute(
            'SELECT t / 3600 * 3600, MIN(hz), MAX(hz), COUNT(*), SUM(hz < ? OR hz > ?) FROM frequency_readings WHERE t >= ? GROUP BY t / 3600',
            (low, high, freq_state["upto"] or 0)):
        freq_hours[hour] = (lowest, highest, count, outside)
        freq_state["upto"] = max(freq_state["upto"] or 0, hour)

def combine(hours):
    """Sums, counts and extremes for a set of hours, plus Powerwall energy (each hour's average power x 1 hour)."""
    out = {"sum": {}, "n": {}, "max": {}, "min": {}, "kwh": {}}
    for hour in hours:
        h = history_hours.get(hour)
        if not h: continue
        for key, value in h["sum"].items():
            out["sum"][key] = out["sum"].get(key, 0) + value
            out["n"][key] = out["n"].get(key, 0) + h["n"][key]
            if key.startswith("pw_"):
                out["kwh"][key] = out["kwh"].get(key, 0) + value / h["n"][key] / 1000
        for key, (value, t) in h["max"].items():
            if key not in out["max"] or value > out["max"][key][0]: out["max"][key] = (value, t)
        for key, (value, t) in h["min"].items():
            if key not in out["min"] or value < out["min"][key][0]: out["min"][key] = (value, t)
    return out

def combine_frequency(hours):
    rows = [freq_hours[h] for h in hours if h in freq_hours]
    if not rows: return None
    count, outside = sum(r[2] for r in rows), sum(r[3] for r in rows)
    return {"min": min(r[0] for r in rows), "max": max(r[1] for r in rows), "readings": count,
            "outside_min": outside * 15 / 60, "outside_pct": outside / count * 100}

def average(c, key):
    return c["sum"][key] / c["n"][key] if c["n"].get(key) else None

@app.route('/history')
def history_page(): return render_template('history.html')

@app.route('/api/history')
def history():
    """Averages for the last 7 days (hourly), 30 days or a year (daily, UK days), plus a summary of the whole range."""
    span = request.args.get('range', '7d')
    days = {'7d': 7, '30d': 30, '1y': 365}.get(span, 7)
    limits = load_config()['frequency']
    low, high = float(limits['thresh_low']), float(limits['thresh_high'])
    now = datetime.now(timezone.utc)
    if days == 7:
        first = int(now.replace(minute=0, second=0, microsecond=0).timestamp()) - 167 * 3600
        buckets = [(first + 3600 * i, [first + 3600 * i]) for i in range(168)]
    else:
        today = datetime.now(LONDON).date()
        buckets = []
        for back in range(days - 1, -1, -1):
            day = today - timedelta(days=back)
            start = int(datetime.combine(day, datetime.min.time(), LONDON).timestamp())
            end = int(datetime.combine(day + timedelta(days=1), datetime.min.time(), LONDON).timestamp())
            buckets.append((start, list(range(start, end, 3600))))

    with history_lock:
        conn = get_db_connection()
        try:
            refresh_history(conn)
            refresh_frequency(conn, low, high)
        finally:
            conn.close()
        # Start at the first bucket with data (the database begins on 23 April 2026)
        while buckets and not any(h in history_hours for h in buckets[0][1]): buckets.pop(0)
        combined = [combine(hours) for _, hours in buckets]
        frequency = [combine_frequency(hours) for _, hours in buckets]
        whole = combine([h for _, hours in buckets for h in hours])
        whole_frequency = combine_frequency([h for _, hours in buckets for h in hours])

    series = lambda key: [average(c, key) for c in combined]
    kwh = lambda key: [c["kwh"].get(key) for c in combined]
    supply = sum(whole["sum"].get("mix:" + k, 0) for k in MIX_KEYS)
    share = lambda *keys: sum(whole["sum"].get("mix:" + k, 0) for k in keys) / supply * 100 if supply else None
    def best(key, highest):
        """The bucket with the highest (or lowest) average for `key`."""
        values = [(v, buckets[i][0]) for i, v in enumerate(series(key)) if v is not None]
        return (max if highest else min)(values) if values else None
    totals = {k: sum(v or 0 for v in kwh(k)) for k in ("pw_solar", "pw_home", "pw_import", "pw_export")}
    return jsonify({
        "range": span, "unit": "hour" if days == 7 else "day", "low": low, "high": high,
        "t": [start for start, _ in buckets],
        "mix": {k: series("mix:" + k) for k in MIX_KEYS + ["battery"]},
        "demand": series("demand"), "net_flow": series("net_flow"), "carbon": series("carbon"),
        "mip": series("mip"), "mip_min": [c["min"].get("mip", (None,))[0] for c in combined], "mip_max": [c["max"].get("mip", (None,))[0] for c in combined],
        "ssp": series("ssp"), "agile_import": series("agile_import"), "agile_export": series("agile_export"),
        "frequency": frequency,
        "home": {k[3:]: kwh(k) for k in ("pw_solar", "pw_home", "pw_import", "pw_export", "pw_batt_in", "pw_batt_out")},
        "temp": series("temp"),
        "summary": {
            "demand_avg": average(whole, "demand"), "demand_peak": whole["max"].get("demand"), "demand_low": whole["min"].get("demand"),
            "wind_max": whole["max"].get("wind"), "solar_max": whole["max"].get("solar"),
            "share": {"wind": share("wind", "lv_wind"), "solar": share("solar"), "gas": share("ccgt", "ocg"), "nuclear": share("nuclear"),
                      "imports": share("imports"), "low_carbon": share("wind", "lv_wind", "solar", "hydro", "nuclear", "biomass")},
            "carbon_avg": average(whole, "carbon"), "carbon_best": best("carbon", False), "carbon_worst": best("carbon", True),
            "mip_avg": average(whole, "mip"), "mip_cheapest": best("mip", False), "mip_dearest": best("mip", True),
            "agile_avg": average(whole, "agile_import"),
            "frequency": whole_frequency,
            "home": {k[3:]: v for k, v in totals.items()},
        },
    })

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

        # An Elexon timeout leaves a row with only Solar/LV Wind in the mix, and a glitch can add up to an impossible total:
        # reuse the last good supply picture
        if prev and (s['total_gen_mw'] - s['embedded_mw'] < 1000 or s['total_gen_mw'] > MAX_PLAUSIBLE_GEN_MW):
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