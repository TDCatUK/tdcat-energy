import csv
import io
import os
import re
import sys
import requests
import sqlite3
import json
from datetime import date, datetime, timedelta, timezone, time
from zoneinfo import ZoneInfo
import pypowerwall
from dotenv import load_dotenv
from sources import SOURCES, parse_utc, source_state

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


# === SOURCE HEALTH (for the /status page) ===
# Each fetch reports how it went; save_health() writes it out with the snapshot row.
HEALTH_TABLES = [
    """CREATE TABLE IF NOT EXISTS source_status (source TEXT PRIMARY KEY, last_ok TEXT, last_attempt TEXT,
        last_error TEXT, last_error_at TEXT, data_time TEXT, fails INTEGER DEFAULT 0)""",
    "CREATE TABLE IF NOT EXISTS source_runs (timestamp TEXT PRIMARY KEY, ok TEXT, failed TEXT, seconds REAL)",
]
HEALTH_KEEP_DAYS = 90
health = {}  # source -> (ok, error, data_time) for this run

def report(source, ok, error=None, data_time=None):
    health[source] = (bool(ok), None if ok else (error or 'No data returned'), data_time)

def short_error(e):
    """A short reason that's safe to show publicly: never the URL (some contain meter numbers) or the response body."""
    if isinstance(e, requests.exceptions.HTTPError) and e.response is not None:
        return f"HTTP {e.response.status_code} {e.response.reason or ''}".strip()
    if isinstance(e, requests.exceptions.Timeout): return 'Timed out'
    if isinstance(e, requests.exceptions.ConnectionError): return "Couldn't connect"
    if isinstance(e, (ValueError, KeyError, IndexError, TypeError, StopIteration)): return 'Unexpected response'
    return type(e).__name__

def save_health(cursor, now_utc, started):
    """Update each reported source's latest state and log which sources worked on this run."""
    stamp = now_utc.strftime('%Y-%m-%dT%H:%M:%SZ')
    for table in HEALTH_TABLES:
        cursor.execute(table)
    for source, (ok, error, data_time) in health.items():
        cursor.execute("INSERT OR IGNORE INTO source_status (source, fails) VALUES (?, 0)", (source,))
        if ok:
            cursor.execute("UPDATE source_status SET last_ok = ?, last_attempt = ?, fails = 0, data_time = COALESCE(?, data_time) WHERE source = ?",
                           (stamp, stamp, data_time, source))
        else:
            cursor.execute("UPDATE source_status SET last_attempt = ?, last_error = ?, last_error_at = ?, fails = fails + 1 WHERE source = ?",
                           (stamp, error, stamp, source))
    cursor.execute("INSERT OR REPLACE INTO source_runs VALUES (?, ?, ?, ?)", (
        stamp, ','.join(k for k, h in health.items() if h[0]), ','.join(k for k, h in health.items() if not h[0]),
        round((datetime.now(timezone.utc) - started).total_seconds(), 1)))
    cursor.execute("DELETE FROM source_runs WHERE timestamp < ?", ((now_utc - timedelta(days=HEALTH_KEEP_DAYS)).strftime('%Y-%m-%dT%H:%M:%SZ'),))


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
            report('cloudflare', False, 'Cloudflare API error')
            return 0, 0, 0

        groups = (data.get('data', {})
                    .get('viewer', {})
                    .get('zones', [{}])[0]
                    .get('httpRequestsAdaptiveGroups', []))

        report('cloudflare', True)
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
        report('cloudflare', False, short_error(e))
        return 0, 0, 0

def fetch_octo_rate(tariff_code, now_utc, timeout=20):
    """The unit rate (p/kWh inc VAT) for the current half-hour, or None if it couldn't be fetched."""
    if not OCTOPUS_BASE_URL or not tariff_code:
        return None

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
            report('octopus_rates', False, 'No rate for the current half-hour')
        else:
            print(f"Octopus {tariff_code}: Empty results from API")
            report('octopus_rates', False, 'No rates returned')

    except requests.exceptions.RequestException as e:
        print(f"Octopus rate HTTP error ({tariff_code}): {e}")
        if 'res' in locals():
            print(f"   Status: {res.status_code}  Body: {res.text[:400]}")
        report('octopus_rates', False, short_error(e))
    except Exception as e:
        print(f"Octopus rate parse error ({tariff_code}): {e}")
        report('octopus_rates', False, short_error(e))

    return None

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
    per_meter, errors = [], []
    for meter_id, serial, meter_type in meters:
        if not meter_id or not serial:
            per_meter.append(None)
            continue
        try:
            per_meter.append(fetch_octo_day_totals(meter_id, serial, meter_type, uk_midnight(today - timedelta(days=3)), uk_midnight(today), timeout))
        except Exception as e:
            print(f"Octopus consumption error ({meter_type} {meter_id[-4:]}): {e}")
            errors.append(short_error(e))
            per_meter.append({})

    def complete(days, day):
        expected = int((uk_midnight(day + timedelta(days=1)) - uk_midnight(day)).total_seconds() // 1800)  # 46 / 48 / 50
        return days.get(day, (0, 0))[1] >= expected

    candidates = [today - timedelta(days=n) for n in (1, 2, 3)]
    chosen = next((d for d in candidates if all(m is None or complete(m, d) for m in per_meter)), None)
    if chosen is None:
        # A meter has stopped reporting: fall back to the latest day with complete import data
        chosen = next((d for d in candidates if per_meter[0] and complete(per_meter[0], d)), None)
        report('octopus_meters', False, errors[0] if errors else 'Not every meter has a complete day in the last 3 days',
               chosen.isoformat() if chosen else None)
    else:
        report('octopus_meters', True, data_time=chosen.isoformat())
    if chosen is None: return 0, 0, 0, ""
    imp, exp, gas = (m.get(chosen, (0, 0))[0] if m else 0 for m in per_meter)
    return imp, exp, gas, chosen.strftime('%d %b')


# === GRID BATTERIES (UNOFFICIAL ESTIMATE) ===
ELEXON_API = "https://data.elexon.co.uk/bmrs/api/v1"
BATTERY_UNITS_FILE = 'battery_units.json'
BATTERY_NG_ID = re.compile(r'^[A-Z0-9]{4}B-\d+$')
BATTERY_NAME = re.compile(r'batter|bess|energy storage', re.I)
NOT_BATTERY_FUELS = {'WIND', 'CCGT', 'OCGT', 'NUCLEAR', 'BIOMASS', 'COAL', 'NPSHYD', 'PS'}

def load_battery_units(timeout=20):
    """Elexon IDs of battery BM units, cached in battery_units.json and refreshed daily.

    Elexon has no battery fuel type, so batteries are recognised by National Grid's
    unit ID convention (fifth character 'B', e.g. BLWNB-1) or a name like 'BESS'.
    """
    cached = []
    try:
        with open(BATTERY_UNITS_FILE) as f: cached = json.load(f)
        if datetime.now().timestamp() - os.path.getmtime(BATTERY_UNITS_FILE) < 86400: return cached
    except (OSError, ValueError): pass
    try:
        units = requests.get(f"{ELEXON_API}/reference/bmunits/all", timeout=timeout).json()
        found = sorted(u['elexonBmUnit'] for u in units
                       if u.get('elexonBmUnit') and u.get('fuelType') not in NOT_BATTERY_FUELS
                       and (BATTERY_NG_ID.match(u.get('nationalGridBmUnit') or '') or BATTERY_NAME.search(u.get('bmUnitName') or '')))
        if found:
            with open(BATTERY_UNITS_FILE, 'w') as f: json.dump(found, f)
            return found
    except Exception as e:
        print(f"Battery unit list error: {e}")
    return cached

def level_at(segment, t):
    """MW level of a PN/BOALF segment at time t (linear between its ends), or None outside it."""
    t0 = datetime.fromisoformat(segment['timeFrom'].replace('Z', '+00:00'))
    t1 = datetime.fromisoformat(segment['timeTo'].replace('Z', '+00:00'))
    if not t0 <= t <= t1: return None
    span = (t1 - t0).total_seconds()
    return segment['levelFrom'] + ((t - t0).total_seconds() / span if span else 0) * (segment['levelTo'] - segment['levelFrom'])

# Acceptances last up to about an hour, so 90 minutes of history covers any still in force
BOALF_LOOKBACK = timedelta(minutes=90)

def fetch_battery_segments(dataset, start, end, units, timeout=20):
    """PN or BOALF segments for the given battery units between start and end."""
    iso = lambda t: t.strftime('%Y-%m-%dT%H:%M:%SZ')
    params = [('from', iso(start)), ('to', iso(end))] + [('bmUnit', u) for u in units]
    res = requests.get(f"{ELEXON_API}/datasets/{dataset}/stream", params=params, timeout=timeout)
    res.raise_for_status()
    data = res.json()
    return data if isinstance(data, list) else data.get('data', [])

def battery_flow_at(t, pn_segments, boalf_segments):
    """(discharging MW, charging MW) at time t: each unit's PN level, replaced by its latest acceptance in force."""
    levels = {}
    for seg in pn_segments:
        mw = level_at(seg, t)
        if mw is not None: levels[seg['bmUnit']] = mw
    accepted = {}
    for seg in boalf_segments:
        mw = level_at(seg, t)
        key = (seg.get('acceptanceTime') or '', seg.get('acceptanceNumber') or 0)
        if mw is not None and (seg['bmUnit'] not in accepted or key > accepted[seg['bmUnit']][0]):
            accepted[seg['bmUnit']] = (key, mw)
    levels.update({unit: mw for unit, (_, mw) in accepted.items()})
    if not levels: return None, None
    return (round(sum(mw for mw in levels.values() if mw > 0)),
            round(sum(-mw for mw in levels.values() if mw < 0)))

def fetch_battery_flow(now_utc, timeout=20):
    """Unofficial estimate of GB grid-battery flow now: (discharging MW, charging MW).

    Each battery's Physical Notification (its own plan), replaced by the latest Bid-Offer
    Acceptance where NESO has redispatched it. Batteries outside the Balancing Mechanism
    aren't visible, so this undercounts. Returns (None, None) if the data isn't available.
    """
    units = load_battery_units(timeout)
    if not units:
        report('batteries', False, 'Battery unit list unavailable')
        return None, None
    try:
        pn = fetch_battery_segments('PN', now_utc - timedelta(minutes=1), now_utc + timedelta(minutes=1), units, timeout)
        boalf = fetch_battery_segments('BOALF', now_utc - BOALF_LOOKBACK, now_utc + timedelta(minutes=1), units, timeout)
        flow = battery_flow_at(now_utc, pn, boalf)
        report('batteries', flow[0] is not None)
        return flow
    except Exception as e:
        print(f"Battery estimate error: {e}")
        report('batteries', False, short_error(e))
        return None, None


# === GRID FREQUENCY (every 15-second reading, not just the latest) ===
# Unix seconds (UTC) -> Hz. About 5,760 readings a day.
FREQ_TABLE = "CREATE TABLE IF NOT EXISTS frequency_readings (t INTEGER PRIMARY KEY, hz REAL) WITHOUT ROWID"
FREQ_HISTORY_START = datetime(2026, 4, 23, tzinfo=timezone.utc)  # when energy_snapshots begins
FREQ_BACKFILL_CHUNK = timedelta(days=7)  # older history fetched per run until it reaches FREQ_HISTORY_START

def fetch_frequency_range(start, end, timeout=20):
    """Elexon's 15-second frequency readings from start to end as a sorted list of (unix seconds, Hz)."""
    fmt = '%Y-%m-%dT%H:%M:%SZ'
    res = requests.get(ELEXON_FREQUENCY_URL, params={'from': start.strftime(fmt), 'to': end.strftime(fmt)}, timeout=timeout)
    res.raise_for_status()
    data = res.json()
    readings = []
    for r in (data if isinstance(data, list) else data.get('data', [])):
        if r.get('frequency') is None or not r.get('measurementTime'): continue
        t = datetime.fromisoformat(r['measurementTime'].replace('Z', '+00:00'))
        readings.append((int(t.timestamp()), float(r['frequency'])))
    return sorted(readings)

def stored_frequency_span():
    """Earliest and latest stored reading (unix seconds), or (None, None)."""
    try:
        conn = sqlite3.connect('grid_data.db')
        try: return conn.execute("SELECT MIN(t), MAX(t) FROM frequency_readings").fetchone()
        finally: conn.close()
    except sqlite3.OperationalError:
        return None, None  # table not created yet

def fetch_frequency(now_utc, timeout=20):
    """New readings since the last stored one, and a chunk of older history while any is missing.

    One request covers every 15-second reading in a range, so keeping them all costs no extra calls.
    The recent window reaches back to the last stored reading (at most a week), which also fills
    the gap after the harvester has been offline.
    """
    earliest, latest = stored_frequency_span()
    start = now_utc - timedelta(minutes=12)  # always enough for a current reading
    if latest: start = min(start, datetime.fromtimestamp(latest, timezone.utc))
    start = max(start, now_utc - timedelta(days=7))
    readings = fetch_frequency_range(start, now_utc, timeout)
    backfill = []
    oldest = datetime.fromtimestamp(earliest, timezone.utc) if earliest else start
    if oldest - FREQ_HISTORY_START > timedelta(minutes=1):
        try: backfill = fetch_frequency_range(max(FREQ_HISTORY_START, oldest - FREQ_BACKFILL_CHUNK), oldest, timeout * 3)
        except Exception as e: print(f"Frequency backfill error: {e}")
    return readings, backfill


# === NATIONAL GAS (GB gas transmission system) ===
NATIONAL_GAS_API = "https://data.nationalgas.com/api"
GAS_STORAGE_SITES = {'ALDBROUGH', 'HILLTOP', 'HOLE HOUSE FARM', 'HOLFORD', 'HORNSEA', 'STUBLACH', 'EASINGTON ROUGH ST'}
GAS_DEMAND_NAMES = {
    'LDZ Offtake Flow': 'Homes & businesses',
    'Power Station Demand Flow': 'Power stations',
    'Industrial Demand Flow': 'Industry',
    'Interconnector Export Demand Flow': 'Exports',
    'Storage Demand Flow': 'Storage injection',
}
# Daily stock levels (kWh in the source, stored as GWh): all storage sites, LNG tanks, and Rough on its own
GAS_DAILY_ITEMS = {'PUBOBJ330': 'storage_stock', 'PUBOBJ333': 'storage_space', 'PUBOBJ336': 'lng_stock', 'PUBOBJ339': 'lng_space',
                   'PUBOBJ2364': 'rough_stock', 'PUBOBJ2428': 'rough_space'}
GAS_DAILY_NAMES = {'Storage, Daily Aggregated Stock level, D+1': 'storage_stock', 'Storage, Daily Aggregated Available Capacity, D+1': 'storage_space',
                   'LNG, Daily Aggregated Stock level, D+1': 'lng_stock', 'LNG, Daily Aggregated Available Capacity, D+1': 'lng_space',
                   'Opening Stock, Rough, Long Range Storage': 'rough_stock', 'Available Capacity, Rough, Long Range Storage': 'rough_space'}
GAS_STOCK_CORE = ('storage_stock', 'storage_space', 'lng_stock', 'lng_space')
# Earliest gas day National Gas publishes these items for
GAS_STORAGE_HISTORY_START = date(2020, 5, 25)

GAS_STORAGE_TABLE = """CREATE TABLE IF NOT EXISTS gas_storage_daily (
    gas_day TEXT PRIMARY KEY,
    storage_stock_gwh REAL,
    storage_space_gwh REAL,
    lng_stock_gwh REAL,
    lng_space_gwh REAL,
    rough_stock_gwh REAL,
    rough_space_gwh REAL
)"""

GAS_TABLE = """CREATE TABLE IF NOT EXISTS gas_snapshots (
    timestamp TEXT PRIMARY KEY,
    flows_time TEXT,
    linepack_mcm REAL,
    supply_mcmd REAL,
    demand_mcmd REAL,
    supply_json TEXT,
    demand_json TEXT,
    stock_gas_day TEXT,
    storage_stock_gwh REAL,
    storage_space_gwh REAL,
    lng_stock_gwh REAL,
    lng_space_gwh REAL
)"""

def fetch_gas_flows(timeout=20):
    """Latest NTS gas flows (2-minute data, published every 12 minutes). Rates in mcm/d, linepack in mcm.

    Supply is grouped by where the gas comes from; 'North Sea' is whatever's left of total supply
    after LNG, storage, the continental pipelines and Norway's Langeled pipeline.
    """
    data = requests.get(f"{NATIONAL_GAS_API}/latest-gas-flows", headers={'User-Agent': 'Mozilla/5.0'}, timeout=timeout).json()['data']
    def latest(row):
        times = [k for k in row if k[:2].isdigit() and ':' in k]
        return (float(row[times[-1]] or 0), times[-1]) if times else (0.0, None)
    def rows(section): return data.get(section, {}).get('data', [])
    entry = {r['SYSTEM ENTRY NAME']: latest(r)[0] for r in rows('Supply from entry points')}
    terminal = {r.get('SYSTEM ENTRY NAME') or r.get('TERMINAL NAME') or next(v for k, v in r.items() if isinstance(v, str) and k != 'qualityIndicator'): latest(r)[0] for r in rows('Supply from terminals')}
    def named(section):
        return {next(v for k, v in r.items() if isinstance(v, str) and k != 'qualityIndicator'): latest(r) for r in rows(section)}
    total_supply, flows_time = next(iter(named('Total supply').values()))
    total_demand, _ = next(iter(named('Total demand').values()))
    linepack, _ = next(iter(named('Actual linepack').values()))

    supply = {
        'LNG': sum(v for k, v in terminal.items() if 'GRAIN' in k.upper() or 'MILFORD' in k.upper()),
        'Storage': sum(v for k, v in entry.items() if k in GAS_STORAGE_SITES),
        'Continent (BBL, IUK)': sum(v for k, v in terminal.items() if 'BACTON IP' in k.upper()),
        'Norway (Langeled)': entry.get('EASINGTON LANGELED', 0),
    }
    supply = {'North Sea (UK & Norway)': max(0, total_supply - sum(supply.values())), **supply}
    demand = {GAS_DEMAND_NAMES.get(k, k): v for k, (v, _) in named('Demand by category').items()}
    return {'flows_time': flows_time, 'linepack_mcm': linepack, 'supply_mcmd': total_supply, 'demand_mcmd': total_demand,
            'supply': supply, 'demand': demand}

def fetch_gas_daily(start, end, timeout=20):
    """Daily stock levels between two gas days: {'YYYY-MM-DD': {item: GWh}}."""
    params = {'applicableFor': 'Y', 'dateType': 'GASDAY', 'latestFlag': 'Y', 'type': 'CSV', 'ids': ','.join(GAS_DAILY_ITEMS),
              'dateFrom': start.isoformat(), 'dateTo': end.isoformat()}
    res = requests.get(f"{NATIONAL_GAS_API}/find-gas-data-download", params=params, headers={'User-Agent': 'Mozilla/5.0'}, timeout=timeout)
    res.raise_for_status()
    by_day = {}
    for row in csv.DictReader(io.StringIO(res.text)):
        key = GAS_DAILY_NAMES.get(row.get('Data Item'))
        if key and row.get('Value'):
            day = datetime.strptime(row['Applicable For'], '%d/%m/%Y').strftime('%Y-%m-%d')
            by_day.setdefault(day, {})[key] = float(row['Value']) / 1e6  # kWh -> GWh
    return by_day

def gas_storage_history_needed():
    """True until gas_storage_daily holds the back history (filled once, on the first run that needs it)."""
    try:
        conn = sqlite3.connect('grid_data.db')
        try: return conn.execute("SELECT COUNT(*) FROM gas_storage_daily").fetchone()[0] < 365
        finally: conn.close()
    except sqlite3.OperationalError:
        return True  # table not created yet

def fetch_gas_stocks(now_utc, timeout=20):
    """Daily stock levels to store (the last few gas days, or the full history if it's missing),
    plus the latest complete day's figures for the snapshot row."""
    today = now_utc.date()
    if gas_storage_history_needed():
        days = {}
        for year in range(GAS_STORAGE_HISTORY_START.year, today.year + 1):
            days.update(fetch_gas_daily(max(date(year, 1, 1), GAS_STORAGE_HISTORY_START), min(date(year, 12, 31), today), timeout=90))
    else:
        days = fetch_gas_daily(today - timedelta(days=4), today, timeout)
    complete = [d for d, v in days.items() if all(k in v for k in GAS_STOCK_CORE)]
    if not complete: return {'daily': days}
    day = max(complete)
    return {'daily': days, 'stock_gas_day': day, **{f"{k}_gwh": days[day][k] for k in GAS_STOCK_CORE}}

def fetch_gas(now_utc, timeout=20):
    """Everything for one gas_snapshots row, or None if the live flows aren't available."""
    try:
        gas = fetch_gas_flows(timeout)
        report('gas', True, data_time=gas['flows_time'])
    except Exception as e:
        print(f"Gas flows error: {e}")
        report('gas', False, short_error(e))
        return None
    try:
        gas.update(fetch_gas_stocks(now_utc, timeout) or {})
        report('gas_storage', 'stock_gas_day' in gas, 'No complete gas day in the last few days', gas.get('stock_gas_day'))
    except Exception as e:
        print(f"Gas stock levels error: {e}")
        report('gas_storage', False, short_error(e))
    return gas


# === NESO HALF-HOURLY DEMAND (for the "When Demand Shifts" and duck-curve charts) ===
NESO_API = "https://api.neso.energy/api/3/action"
# Demand Data Update: about five weeks of actuals (plus a week of forecasts), refreshed each morning
NESO_DEMAND_UPDATE = '177f6fa4-ae49-4182-81ea-0c6b35f26ca6'
DUCK_FIRST_YEAR = 2010

DEMAND_TABLES = [
    """CREATE TABLE IF NOT EXISTS neso_demand_hh (
        settlement_date TEXT, settlement_period INTEGER, nd REAL, tsd REAL, embedded_solar REAL, embedded_wind REAL,
        PRIMARY KEY (settlement_date, settlement_period))""",
    """CREATE TABLE IF NOT EXISTS duck_profiles (
        year INTEGER, month INTEGER, settlement_period INTEGER, nd REAL, embedded_solar REAL, days INTEGER,
        PRIMARY KEY (year, month, settlement_period))""",
    """CREATE TABLE IF NOT EXISTS duck_records (
        year INTEGER PRIMARY KEY, solar_share_pct REAL, share_date TEXT, share_period INTEGER,
        share_solar REAL, share_nd REAL, halfhours_solar_over_nd INTEGER)""",
    """CREATE TABLE IF NOT EXISTS fetch_log (name TEXT PRIMARY KEY, fetched_at TEXT)""",
]

def fetch_due(name, hours):
    """True if `name` was last fetched more than `hours` ago, or never."""
    try:
        conn = sqlite3.connect('grid_data.db')
        try: row = conn.execute("SELECT fetched_at FROM fetch_log WHERE name = ?", (name,)).fetchone()
        finally: conn.close()
    except sqlite3.OperationalError:
        return True  # table not created yet
    return not row or datetime.now(timezone.utc) - datetime.fromisoformat(row[0]) > timedelta(hours=hours)

def neso_sql(sql, timeout=120):
    """Run a read-only SQL query on NESO's data portal. (Its plain search API fails when asked for specific fields.)"""
    res = requests.get(f"{NESO_API}/datastore_search_sql", params={'sql': sql}, timeout=timeout).json()
    if not res.get('success'): raise ValueError(str(res.get('error'))[:200])
    return res['result']['records']

def parse_settlement_date(value):
    """NESO settlement dates come as 2026-10-05, 01-JAN-2020 or 01-Jan-23 depending on the year."""
    text = str(value).strip()
    if text[:4].isdigit(): text = text[:10]  # drop any time part from ISO dates (not by splitting on 'T', which is in 'OCT')
    for fmt in ('%Y-%m-%d', '%d-%b-%Y', '%d-%b-%y'):
        try: return datetime.strptime(text, fmt).date()
        except ValueError: pass
    return None

def fetch_recent_demand(timeout=60):
    """Half-hourly actuals for the last few weeks: (date, period, ND, TSD, embedded solar, embedded wind) in MW."""
    sql = ('SELECT "SETTLEMENT_DATE", "SETTLEMENT_PERIOD", "ND", "TSD", "EMBEDDED_SOLAR_GENERATION", "EMBEDDED_WIND_GENERATION" '
           f'FROM "{NESO_DEMAND_UPDATE}" WHERE "FORECAST_ACTUAL_INDICATOR" = \'A\'')
    rows = []
    for r in neso_sql(sql, timeout):
        day = parse_settlement_date(r['SETTLEMENT_DATE'])
        if day and r['ND']:
            rows.append((day.isoformat(), int(r['SETTLEMENT_PERIOD']), float(r['ND']), float(r['TSD'] or 0),
                         float(r['EMBEDDED_SOLAR_GENERATION'] or 0), float(r['EMBEDDED_WIND_GENERATION'] or 0)))
    return rows

def summarise_demand_year(records):
    """Average grid demand (ND) and rooftop solar by month and half-hour, plus the year's solar records."""
    sums, best, over = {}, None, 0
    for r in records:
        day, period = parse_settlement_date(r['SETTLEMENT_DATE']), int(r['SETTLEMENT_PERIOD'])
        nd, solar = float(r['ND'] or 0), float(r.get('EMBEDDED_SOLAR_GENERATION') or 0)
        if not day or period > 48 or nd <= 0: continue
        total = sums.setdefault((day.month, period), [0.0, 0.0, 0])
        total[0] += nd; total[1] += solar; total[2] += 1
        share = solar / (nd + solar)
        if best is None or share > best[0]: best = (share, day.isoformat(), period, solar, nd)
        if solar > nd: over += 1
    profiles = [(month, period, t[0] / t[2], t[1] / t[2], t[2]) for (month, period), t in sorted(sums.items())]
    return profiles, best, over

def recent_demand_rows(since, recent=None):
    """Demand Data Update rows on or after `since` (stored ones plus any just fetched) as (date, period, ND, solar)."""
    rows = {}
    try:
        conn = sqlite3.connect('grid_data.db')
        try:
            for day, period, nd, solar in conn.execute(
                    "SELECT settlement_date, settlement_period, nd, embedded_solar FROM neso_demand_hh WHERE settlement_date >= ?", (since,)):
                rows[(day, period)] = (day, period, nd, solar)
        finally: conn.close()
    except sqlite3.OperationalError:
        pass  # table not created yet
    for day, period, nd, tsd, solar, wind in (recent or []):
        if day >= since: rows[(day, period)] = (day, period, nd, solar)
    return list(rows.values())

def fetch_demand_history(now_utc, recent=None, timeout=120):
    """Duck-curve summaries for each year since DUCK_FIRST_YEAR not yet stored, plus the current year.

    NESO's yearly file runs a few weeks behind, so for the current year every day after the file ends
    is filled in from the fresher Demand Data Update rows. New records then show up within a day,
    and no half-hour is counted twice.
    """
    try:
        conn = sqlite3.connect('grid_data.db')
        try: have = {y for (y,) in conn.execute("SELECT DISTINCT year FROM duck_profiles")}
        finally: conn.close()
    except sqlite3.OperationalError:
        have = set()
    package = requests.get(f"{NESO_API}/package_show", params={'id': 'historic-demand-data'}, timeout=timeout).json()['result']
    resources = {int(r['name'].split()[-1]): r['id'] for r in package['resources']
                 if r['name'].startswith('Historic Demand Data') and r.get('datastore_active')}
    years = {}
    for year in sorted(set(resources) | {now_utc.year}):
        if year < DUCK_FIRST_YEAR or (year in have and year != now_utc.year): continue
        records = []
        if year in resources:
            sql = f'SELECT "SETTLEMENT_DATE", "SETTLEMENT_PERIOD", "ND", "EMBEDDED_SOLAR_GENERATION" FROM "{resources[year]}"'
            records = neso_sql(sql, timeout)
        if year == now_utc.year:
            dates = [d for d in (parse_settlement_date(r['SETTLEMENT_DATE']) for r in records) if d]
            file_ends = max(dates).isoformat() if dates else f'{year - 1}-12-31'
            records += [{'SETTLEMENT_DATE': day, 'SETTLEMENT_PERIOD': period, 'ND': nd, 'EMBEDDED_SOLAR_GENERATION': solar}
                        for day, period, nd, solar in recent_demand_rows(f'{year}-01-01', recent) if day > file_ends]
        if records:
            years[year] = summarise_demand_year(records)
    return years

def fetch_neso_demand(timeout=60):
    """Recent half-hourly demand (every 3 hours) and the yearly duck-curve summaries (daily), when due."""
    now_utc = datetime.now(timezone.utc)
    out = {'attempted': []}
    if fetch_due('neso_recent', 3):
        out['attempted'].append('neso_recent')
        try:
            out['recent'] = fetch_recent_demand(timeout)
            report('neso_demand', out['recent'], 'No rows returned', max((r[0] for r in out['recent']), default=None))
        except Exception as e:
            print(f"NESO recent demand error: {e}")
            report('neso_demand', False, short_error(e))
    if fetch_due('neso_history', 24):
        out['attempted'].append('neso_history')
        try:
            out['history'] = fetch_demand_history(now_utc, out.get('recent'))
            report('neso_history', True)
        except Exception as e:
            print(f"NESO demand history error: {e}")
            report('neso_history', False, short_error(e))
    return out


# === PRICE HISTORY (verified half-hourly records, for the History page) ===
PRICE_HISTORY_START = datetime(2026, 4, 23, tzinfo=timezone.utc)  # when energy_snapshots begins
# Every published market index half-hour, as Elexon publishes it (some periods appear hours late, mostly at weekends).
# Volume 0 means nothing traded and the price is a placeholder, so readers use volume > 0.
MARKET_INDEX_TABLE = """CREATE TABLE IF NOT EXISTS market_index_hh (
    period_start TEXT, provider TEXT, settlement_date TEXT, settlement_period INTEGER, price REAL, volume REAL,
    PRIMARY KEY (period_start, provider))"""

def market_index_rows(data):
    """Elexon market-index items as market_index_hh rows."""
    return [(r['startTime'], r['dataProvider'], r.get('settlementDate'), r.get('settlementPeriod'), float(r['price']), float(r.get('volume') or 0))
            for r in data if r.get('startTime') and r.get('dataProvider') and r.get('price') is not None]

def fetch_market_index_backfill(now_utc, timeout=20):
    """Every half-hour from PRICE_HISTORY_START to 2 days ago (the live fetch covers the last 2 days), 7 days per
    request (Elexon's limit). Runs until it has succeeded once (logged as 'midp_backfill'); about 25 quick requests."""
    if not ELEXON_MARKET_INDEX_URL or not fetch_due('midp_backfill', 24 * 365 * 10): return None
    fmt = '%Y-%m-%dT%H:%M:%SZ'
    rows, end = [], now_utc - timedelta(days=2)
    while end > PRICE_HISTORY_START:
        start = max(PRICE_HISTORY_START, end - timedelta(days=7))
        res = requests.get(ELEXON_MARKET_INDEX_URL, params={'from': start.strftime(fmt), 'to': end.strftime(fmt)}, timeout=timeout)
        res.raise_for_status()
        rows += market_index_rows(res.json().get('data', []))
        end = start
    return rows


# === UPCOMING AGILE PRICES AND CARBON FORECAST (every 30 minutes) ===
FORECAST_TABLES = [
    "CREATE TABLE IF NOT EXISTS agile_rates (valid_from TEXT PRIMARY KEY, valid_to TEXT, import_p REAL, export_p REAL)",
    "CREATE TABLE IF NOT EXISTS carbon_forecast (period_from TEXT PRIMARY KEY, forecast REAL, actual REAL, index_label TEXT)",
    # National wind and solar output forecasts (MW), the weather-driven part of the carbon forecast
    "CREATE TABLE IF NOT EXISTS generation_forecast (period_from TEXT PRIMARY KEY, wind_mw REAL, embedded_wind_mw REAL, solar_mw REAL)",
]
WINDFOR_URL = f"{ELEXON_API}/datasets/WINDFOR"
NESO_EMBEDDED_FORECAST = 'db6c038f-98af-4570-ab60-24d71ebd0ae5'  # embedded wind and solar forecasts, half-hourly, about 2 weeks ahead

def fetch_agile_rates(tariff_code, since, until=None, timeout=20):
    """Published half-hourly unit rates (p/kWh inc VAT) from `since` (to `until`), as {valid_from: (valid_to, rate)}.

    Octopus publishes the next day's Agile rates (to 23:00 UK time) at about 4pm, and keeps every past rate.
    Long ranges come back in pages of up to 1,500, which are followed.
    """
    url = f"{OCTOPUS_BASE_URL.rstrip('/')}/products/{tariff_code}/electricity-tariffs/E-1R-{tariff_code}-{OCT_REGION}/standard-unit-rates/"
    params = {'period_from': since.strftime('%Y-%m-%dT%H:%M:%SZ'), 'page_size': 1500}
    if until: params['period_to'] = until.strftime('%Y-%m-%dT%H:%M:%SZ')
    rates = {}
    while url:
        res = requests.get(url, params=params, timeout=timeout)
        res.raise_for_status()
        body = res.json()
        rates.update({r['valid_from']: (r.get('valid_to'), float(r['value_inc_vat'])) for r in body.get('results', []) if r.get('valid_from')})
        url, params = body.get('next'), None  # the next link carries its own query
    return rates

def merge_agile(imp, exp):
    """Import and export rates as agile_rates rows: (valid_from, valid_to, import p, export p)."""
    return [(vf, (imp.get(vf) or exp.get(vf))[0], imp.get(vf, (None, None))[1], exp.get(vf, (None, None))[1])
            for vf in sorted(set(imp) | set(exp))]

def fetch_carbon_forecast(since, timeout=20):
    """National carbon intensity (gCO2/kWh) for each half-hour of the 48 hours from `since`: (from, forecast, actual, index)."""
    res = requests.get(f"{CARBON_INTENSITY_URL.rstrip('/')}/{since.strftime('%Y-%m-%dT%H:%MZ')}/fw48h", timeout=timeout)
    res.raise_for_status()
    rows = []
    for r in res.json().get('data', []):
        intensity = r.get('intensity') or {}
        rows.append((r['from'].replace('Z', ':00Z'), intensity.get('forecast'), intensity.get('actual'), intensity.get('index')))
    return rows

def fetch_generation_forecast(timeout=20):
    """National wind and solar output forecast per half-hour: (start, transmission wind MW, embedded wind MW, solar MW).

    Wind farms on the transmission network come from Elexon's WINDFOR (hourly, about two days ahead, so both
    half-hours of an hour get its value). Embedded (distribution-connected) wind and solar, which is nearly all of
    GB's solar, come from NESO's forecast. Only half-hours with both are kept.
    """
    res = requests.get(WINDFOR_URL, timeout=timeout)
    res.raise_for_status()
    wind = {}
    for r in res.json().get('data', []):
        hour = datetime.fromisoformat(r['startTime'].replace('Z', '+00:00'))
        for minutes in (0, 30):
            wind[hour + timedelta(minutes=minutes)] = float(r['generation'])
    res = requests.get(f"{NESO_API}/datastore_search", params={'resource_id': NESO_EMBEDDED_FORECAST, 'limit': 2000}, timeout=timeout)
    res.raise_for_status()
    rows = []
    for r in res.json()['result']['records']:
        day = parse_settlement_date(r.get('SETTLEMENT_DATE'))
        if not day or not r.get('SETTLEMENT_PERIOD'): continue
        # Settlement periods count UK-time half-hours from midnight (TIME_GMT is the period's end)
        start = datetime.combine(day, time.min, LONDON).astimezone(timezone.utc) + timedelta(minutes=30 * (int(r['SETTLEMENT_PERIOD']) - 1))
        if start in wind:
            rows.append((start.strftime('%Y-%m-%dT%H:%M:%SZ'), wind[start], float(r.get('EMBEDDED_WIND_FORECAST') or 0), float(r.get('EMBEDDED_SOLAR_FORECAST') or 0)))
    return sorted(rows)

def fetch_forecasts(now_utc, timeout=20):
    """Agile import/export rates (from 2 days back, which also fills any short gap) and the carbon forecast, when due.
    The first time, agile_rates is also back-filled to PRICE_HISTORY_START for the History page."""
    out = {'attempted': [], 'done': []}
    if not fetch_due('forecasts', 0.4): return out  # each half-hour (runs are 5 minutes apart)
    out['attempted'].append('forecasts')
    half_hour = now_utc.replace(minute=now_utc.minute // 30 * 30, second=0, microsecond=0)
    if OCTOPUS_BASE_URL and OCT_IMP_TARIFF:
        try:
            since = half_hour - timedelta(days=2)
            imp = fetch_agile_rates(OCT_IMP_TARIFF, since, timeout=timeout)
            exp = fetch_agile_rates(OCT_EXP_TARIFF, since, timeout=timeout) if OCT_EXP_TARIFF else {}
            out['agile'] = merge_agile(imp, exp)
            report('agile_forecast', out['agile'], 'No rates published', max((r[1] or r[0] for r in out['agile']), default=None))
        except Exception as e:
            print(f"Agile rates error: {e}")
            report('agile_forecast', False, short_error(e))
        if fetch_due('agile_backfill', 24 * 365 * 10):  # once, until it succeeds
            try:
                imp = fetch_agile_rates(OCT_IMP_TARIFF, PRICE_HISTORY_START, half_hour, timeout * 3)
                exp = fetch_agile_rates(OCT_EXP_TARIFF, PRICE_HISTORY_START, half_hour, timeout * 3) if OCT_EXP_TARIFF else {}
                out['agile'] = merge_agile(imp, exp) + out.get('agile', [])
                out['done'].append('agile_backfill')
            except Exception as e:
                print(f"Agile back-fill error: {e}")
    try:
        out['generation'] = fetch_generation_forecast(timeout)
        report('gen_forecast', out['generation'], 'No forecast rows', max((r[0] for r in out['generation']), default=None))
    except Exception as e:
        print(f"Wind and solar forecast error: {e}")
        report('gen_forecast', False, short_error(e))
    if CARBON_INTENSITY_URL:
        try:
            out['carbon'] = fetch_carbon_forecast(half_hour, timeout)
            report('carbon_forecast', out['carbon'], 'No forecast returned', max((r[0] for r in out['carbon']), default=None))
        except Exception as e:
            print(f"Carbon forecast error: {e}")
            report('carbon_forecast', False, short_error(e))
    return out


# === ALERTS (ntfy push notifications) ===
# Settings in .env: NTFY_TOPIC (required to send anything), and optionally NTFY_TOKEN (for a reserved topic),
# NTFY_SERVER (default https://ntfy.sh) and ALERT_DAILY_HOUR (UK hour for the daily all-clear, default 8).
NTFY_SERVER = (os.getenv("NTFY_SERVER") or "https://ntfy.sh").rstrip('/')
NTFY_TOPIC = os.getenv("NTFY_TOPIC")
NTFY_TOKEN = os.getenv("NTFY_TOKEN")
ALERT_DAILY_HOUR = int(os.getenv("ALERT_DAILY_HOUR") or 8)
STATUS_URL = f"https://{HOSTNAME}/status"
# The state each source was last reported as ('ok' or 'fail'), and since when it last worked if failing
ALERT_TABLE = "CREATE TABLE IF NOT EXISTS alert_state (source TEXT PRIMARY KEY, state TEXT, since TEXT)"

def notify(title, message, priority=3, tags=()):
    """Push a notification to the ntfy topic. True if ntfy accepted it. Titles are sent as headers, so keep them plain text."""
    if not NTFY_TOPIC: return False
    headers = {'Title': title, 'Priority': str(priority), 'Click': STATUS_URL}
    if tags: headers['Tags'] = ','.join(tags)
    if NTFY_TOKEN: headers['Authorization'] = f"Bearer {NTFY_TOKEN}"
    try:
        requests.post(f"{NTFY_SERVER}/{NTFY_TOPIC}", data=message.encode('utf-8'), headers=headers, timeout=10).raise_for_status()
        return True
    except Exception as e:
        print(f"ntfy error: {short_error(e)}")
        return False

def duration_text(seconds):
    mins = max(1, round(seconds / 60))
    if mins < 60: return f"{mins} min"
    if mins < 48 * 60: return f"{mins // 60} h {mins % 60:02d} min"
    return f"{round(mins / 1440)} days"

def check_alerts(now_utc, online=True):
    """After each run: one notification listing sources that have just gone red, one when they recover, and a daily all-clear.

    Uses the same rules as the Status page (sources.py), so a source alerts when its dot turns red:
    3 failures in a row, or nothing good for 12 of its intervals. Amber never alerts. If a send fails
    it's retried next run. While the internet is down nothing can be sent, so newly failing sources are
    recorded quietly and their recovery is reported once it's back.
    """
    if not NTFY_TOPIC: return
    try:
        conn = sqlite3.connect('grid_data.db')
        conn.row_factory = sqlite3.Row
        try:
            conn.execute(ALERT_TABLE)
            status = {r['source']: r for r in conn.execute('SELECT * FROM source_status')}
            alerted = {r['source']: r for r in conn.execute('SELECT * FROM alert_state')}
            names, states, failing, recovered = {}, {}, [], []
            for _, sources in SOURCES:
                for key, name, _, every in sources:
                    state = source_state(status.get(key), every, now_utc)
                    if state == 'unknown': continue
                    names[key], states[key] = name, state
                    before = alerted[key]['state'] if key in alerted else None
                    if state == 'fail' and before != 'fail': failing.append(key)
                    elif state == 'ok' and before == 'fail': recovered.append(key)  # amber after red isn't a recovery yet
                    elif before is None: conn.execute("INSERT INTO alert_state VALUES (?, 'ok', NULL)", (key,))

            def ago(key):
                last_ok = status[key]['last_ok']
                return f"last worked {duration_text((now_utc - parse_utc(last_ok)).total_seconds())} ago" if last_ok else "hasn't worked yet"
            if failing:
                lines = [f"{names[k]}: {status[k]['last_error'] if status[k]['fails'] else 'no new data'} ({ago(k)})" for k in failing]
                title = f"{names[failing[0]]} is failing" if len(failing) == 1 else f"{len(failing)} data sources are failing"
                if not online or notify(title, '\n'.join(lines), priority=4, tags=['rotating_light']):
                    conn.executemany("INSERT OR REPLACE INTO alert_state VALUES (?, 'fail', ?)", [(k, status[k]['last_ok']) for k in failing])
            if recovered and online:
                def down_for(k):
                    since = alerted[k]['since']
                    return f"back after {duration_text((now_utc - parse_utc(since)).total_seconds())}" if since else "back"
                title = f"{names[recovered[0]]} is working again" if len(recovered) == 1 else f"{len(recovered)} data sources are working again"
                if notify(title, '\n'.join(f"{names[k]}: {down_for(k)}" for k in recovered), tags=['white_check_mark']):
                    conn.executemany("INSERT OR REPLACE INTO alert_state VALUES (?, 'ok', NULL)", [(k,) for k in recovered])

            # Daily all-clear, so silence means something's wrong (OTTO, the network or the harvester itself)
            uk_now = now_utc.astimezone(LONDON)
            last = conn.execute("SELECT fetched_at FROM fetch_log WHERE name = 'alert_daily'").fetchone()
            if online and uk_now.hour >= ALERT_DAILY_HOUR and (not last or datetime.fromisoformat(last[0]).astimezone(LONDON).date() != uk_now.date()):
                day_ago = (now_utc - timedelta(days=1)).strftime('%Y-%m-%dT%H:%M:%SZ')
                runs, seconds = conn.execute("SELECT COUNT(*), AVG(seconds) FROM source_runs WHERE timestamp >= ?", (day_ago,)).fetchone()
                blips = {}
                for (failed,) in conn.execute("SELECT failed FROM source_runs WHERE timestamp >= ? AND failed != ''", (day_ago,)):
                    for k in failed.split(','):
                        blips[k] = blips.get(k, 0) + 1
                problems = [k for k, s in states.items() if s != 'ok']
                lines = [f"{runs} harvester runs in the last 24 hours, averaging {seconds or 0:.1f} s."]
                lines += [f"{names[k]}: {'failing' if states[k] == 'fail' else 'needs a look'} ({status[k]['last_error'] or 'late'})" for k in problems]
                brief = [f"{names.get(k, k)} ×{n}" for k, n in sorted(blips.items(), key=lambda kv: -kv[1]) if k not in problems]
                lines.append(f"Brief failures that recovered: {', '.join(brief)}." if brief else "No failed fetches.")
                title = f"Daily check: all {len(states)} sources OK" if not problems else f"Daily check: {len(problems)} of {len(states)} sources need a look"
                if notify(title, '\n'.join(lines), priority=3 if not problems else 4, tags=['sunny'] if not problems else ['warning']):
                    conn.execute("INSERT OR REPLACE INTO fetch_log VALUES ('alert_daily', ?)", (now_utc.isoformat(),))
            conn.commit()
        finally:
            conn.close()
    except Exception as e:
        print(f"Alert check error: {e}")


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
    started = datetime.now(timezone.utc)

    try:
        req_timeout = 20
        now_utc = datetime.now(timezone.utc)

        # === OFFLINE / LOCAL-ONLY MODE ===
        try:
            # Check if the wider internet is alive
            requests.get("https://1.1.1.1", timeout=5)
            report('internet', True)
        except requests.exceptions.RequestException:
            print("-> ISP Offline. Switching to Local-Only mode (Forward-Filling Grid Data).")
            report('internet', False, 'Offline')
            
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
                            report('powerwall', True)
                        else:
                            report('powerwall', False, 'No readings')
                    except Exception as pw_e:
                        print(f"PW Offline too: {pw_e}")
                        report('powerwall', False, short_error(pw_e))

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
                     cf_visits_24h, cf_requests_24h, cf_bytes_24h, embedded_wind_mw,
                     bess_discharge_mw, bess_charge_mw)
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
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
                    last.get('embedded_wind_mw', 0),
                    last.get('bess_discharge_mw'), last.get('bess_charge_mw')
                ))
                save_health(cursor, now_utc, started)
                conn.commit()
                conn.close()
                print("-> Success! Local-Only row added.")
                check_alerts(now_utc, online=False)
                return # <-- EXITS THE SCRIPT HERE SO EXTERNAL APIS ARE SKIPPED
                
            except Exception as e:
                print(f"-> Local-Only Error: {e}")
                return

        # === NORMAL ONLINE MODE CONTINUES HERE ===
        
        # === OCTOPUS API ===
        oct_imp_pence = fetch_octo_rate(OCT_IMP_TARIFF, now_utc, req_timeout)
        oct_exp_pence = fetch_octo_rate(OCT_EXP_TARIFF, now_utc, req_timeout)
        if oct_imp_pence is not None and oct_exp_pence is not None: report('octopus_rates', True)
        oct_imp_pence, oct_exp_pence = oct_imp_pence or 0.0, oct_exp_pence or 0.0
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
            report('weather', True)

        except Exception as e:                       # ← now you’ll actually SEE why it fails
            print(f"Weather fetch failed: {type(e).__name__}: {e}")
            report('weather', False, short_error(e))
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
            report('carbon', carbon_intensity, 'No figure for this half-hour', ci_res['data'][0].get('from'))
        except Exception as e:
            carbon_intensity = 0
            report('carbon', False, short_error(e))


        # === DEMAND API ===
        try:
            demand_res = requests.get(ELEXON_DEMAND_URL, timeout=req_timeout).json() if ELEXON_DEMAND_URL else {}
            latest_item = max(demand_res.get('data', [{'demand': 0}]), key=lambda x: x.get('startTime', ''))
            latest_demand = latest_item['demand']
            report('itsdo', latest_demand > 0, 'No demand figure', latest_item.get('startTime'))
        except Exception as e:
            latest_demand = 0
            report('itsdo', False, short_error(e))


         # === GRID FREQUENCY API (all 15-second readings since the last run) ===
        freq_readings, freq_backfill = [], []
        try:
            if not ELEXON_FREQUENCY_URL:
                raise ValueError("ELEXON_FREQUENCY_URL not set in .env")
            freq_readings, freq_backfill = fetch_frequency(now_utc, req_timeout)
            grid_frequency = freq_readings[-1][1] if freq_readings else 50.0
            report('frequency', freq_readings, 'No readings in the last 12 minutes',
                   datetime.fromtimestamp(freq_readings[-1][0], timezone.utc).strftime('%Y-%m-%dT%H:%M:%SZ') if freq_readings else None)
        except Exception as e:
            print(f"Frequency error: {e}")
            grid_frequency = 50.0
            report('frequency', False, short_error(e))



        # === SOLAR API ===
        try:
            solar_row = requests.get(SHEFFIELD_SOLAR_URL, timeout=req_timeout).json()['data'][0] if SHEFFIELD_SOLAR_URL else [None, None, 0]
            solar_mw = solar_row[2] or 0
            if SHEFFIELD_SOLAR_URL: report('pvlive', True, data_time=solar_row[1])
        except Exception as e:
            solar_mw = 0
            report('pvlive', False, short_error(e))


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
                report('lv_wind', True, data_time=closest_record[0].strftime('%Y-%m-%dT%H:%M:%SZ'))
            else:
                embedded_wind_mw = 0
                report('lv_wind', False, 'No forecast rows')
                
        except Exception as e:
            print(f"LV Wind error: {e}")
            embedded_wind_mw = 0
            report('lv_wind', False, short_error(e))



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
                report('fuelinst', True, data_time=latest_time)
            else:
                report('fuelinst', False, 'No data returned')
        except Exception as e:
            report('fuelinst', False, short_error(e))

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
                            report('system_prices', True, data_time=item.get('startTime'))
                            break
                else:
                    report('system_prices', False, 'No prices published today or yesterday')
        except Exception as e:
            print(f"System price error: {e}")
            report('system_prices', False, short_error(e))


        # === DAY-AHEAD & MARKET INDEX PRICES (MIDP PROXY) ===
        latest_day_ahead_price = 0.0
        latest_market_index_price = 0.0
        midp_history = []
        try:
            if ELEXON_MARKET_INDEX_URL:
                # One request covers the last 2 days: every half-hour goes into market_index_hh (Elexon publishes some
                # late, so later runs fill them in), and the live price is the newest traded one in the last 6 hours
                window_start = now_utc - timedelta(days=2)
                live_since = (now_utc - timedelta(hours=6)).strftime('%Y-%m-%dT%H:%M:%SZ')
                end_time = (now_utc + timedelta(hours=3)).strftime('%Y-%m-%dT%H:%M:%SZ')
                res = requests.get(ELEXON_MARKET_INDEX_URL, params={
                    'from': window_start.strftime('%Y-%m-%dT%H:%M:%SZ'),
                    'to': end_time,
                }, timeout=req_timeout)

                if res.status_code == 200:
                    data = res.json().get('data', [])
                    if data:
                        midp_history = market_index_rows(data)
                        data.sort(key=lambda x: x.get('startTime', ''), reverse=True)
                        now_str = now_utc.strftime('%Y-%m-%dT%H:%M:%SZ')
                        
                        # A price with zero traded volume is a placeholder 0, not a real price
                        current_period_data = [item for item in data if live_since <= item.get('startTime', '') <= now_str and (item.get('volume') or 0) > 0]

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
                        report('market_index', apx_price is not None or n2ex_price is not None, 'No traded price in the last 6 hours',
                               next((item.get('startTime') for item in current_period_data if item.get('price') is not None), None))
                    else:
                        report('market_index', False, 'No data returned')
                else:
                    report('market_index', False, f"HTTP {res.status_code}")
                        
        except Exception as e:
            print(f"Pricing error: {e}")
            report('market_index', False, short_error(e))



        # === POWERWALL API ===
        pw_solar, pw_home, pw_battery, pw_grid, pw_level, pw_grid_status = 0, 0, 0, 0, 0, "UNKNOWN"
        try:
            if PW_IP and PW_PASSWORD:
                pw = pypowerwall.Powerwall(host=PW_IP, password=PW_PASSWORD, email=PW_EMAIL)
                pw_power = pw.power()
                if sum(pw_power.values()) != 0 or pw.level() > 0:
                    pw_solar, pw_home, pw_battery, pw_grid, pw_level, pw_grid_status = pw_power.get('solar', 0), pw_power.get('load', 0), pw_power.get('battery', 0), pw_power.get('site', 0), pw.level(), pw.grid_status()       
                    report('powerwall', True)
                else:
                    report('powerwall', False, 'No readings')
        except Exception as e:
            report('powerwall', False, short_error(e))

        # === CLOUDFLARE API ===
        cf_visits, cf_requests, cf_bytes = get_cloudflare_stats(debug=False)

        # === GRID BATTERIES (UNOFFICIAL ESTIMATE) ===
        bess_discharge_mw, bess_charge_mw = fetch_battery_flow(now_utc, req_timeout)

        # === NATIONAL GAS ===
        gas = fetch_gas(now_utc, req_timeout)

        # === NESO HALF-HOURLY DEMAND (fetched every few hours, not every run) ===
        neso_demand = fetch_neso_demand()

        # === UPCOMING AGILE PRICES AND CARBON FORECAST (every 30 minutes) ===
        forecasts = fetch_forecasts(now_utc, req_timeout)

        # === MARKET INDEX HISTORY BACK-FILL (once) ===
        midp_done = []
        try:
            backfill = fetch_market_index_backfill(now_utc, req_timeout)
            if backfill is not None:
                midp_history += backfill
                midp_done.append('midp_backfill')
        except Exception as e:
            print(f"Market index back-fill error: {e}")

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
             cf_visits_24h, cf_requests_24h, cf_bytes_24h, embedded_wind_mw,
             bess_discharge_mw, bess_charge_mw)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        ''', (
            now_utc.strftime('%Y-%m-%dT%H:%M:%SZ'),
            carbon_intensity, true_demand, total_generation, total_net_flow,
            latest_price, latest_day_ahead_price, latest_market_index_price, grid_frequency, latest_niv,
            json.dumps(generation), json.dumps(interconnectors),
            pw_solar, pw_home, pw_battery, pw_grid, pw_level, pw_grid_status,
            temp_c, wind_mph, daylight_secs, cloud_cover, 
            oct_imp_pence, oct_exp_pence, oct_yest_imp, oct_yest_exp, oct_yest_gas, oct_final_date,
            cf_visits, cf_requests, cf_bytes,
            embedded_wind_mw,
            bess_discharge_mw, bess_charge_mw
        ))
        if gas:
            cursor.execute(GAS_TABLE)
            cursor.execute('''
                INSERT OR REPLACE INTO gas_snapshots
                (timestamp, flows_time, linepack_mcm, supply_mcmd, demand_mcmd, supply_json, demand_json,
                 stock_gas_day, storage_stock_gwh, storage_space_gwh, lng_stock_gwh, lng_space_gwh)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            ''', (
                now_utc.strftime('%Y-%m-%dT%H:%M:%SZ'), gas['flows_time'], gas['linepack_mcm'], gas['supply_mcmd'], gas['demand_mcmd'],
                json.dumps(gas['supply']), json.dumps(gas['demand']),
                gas.get('stock_gas_day'), gas.get('storage_stock_gwh'), gas.get('storage_space_gwh'), gas.get('lng_stock_gwh'), gas.get('lng_space_gwh')
            ))
            cursor.execute(GAS_STORAGE_TABLE)
            cursor.executemany('''
                INSERT OR REPLACE INTO gas_storage_daily
                (gas_day, storage_stock_gwh, storage_space_gwh, lng_stock_gwh, lng_space_gwh, rough_stock_gwh, rough_space_gwh)
                VALUES (?, ?, ?, ?, ?, ?, ?)
            ''', [(day, v.get('storage_stock'), v.get('storage_space'), v.get('lng_stock'), v.get('lng_space'), v.get('rough_stock'), v.get('rough_space'))
                  for day, v in gas.get('daily', {}).items()])
        cursor.execute(FREQ_TABLE)
        cursor.executemany('INSERT OR IGNORE INTO frequency_readings VALUES (?, ?)', freq_readings + freq_backfill)
        for table in DEMAND_TABLES:
            cursor.execute(table)
        if neso_demand.get('recent'):
            cursor.executemany('INSERT OR REPLACE INTO neso_demand_hh VALUES (?, ?, ?, ?, ?, ?)', neso_demand['recent'])
        for year, (profiles, best, over) in neso_demand.get('history', {}).items():
            cursor.execute('DELETE FROM duck_profiles WHERE year = ?', (year,))
            cursor.executemany('INSERT INTO duck_profiles VALUES (?, ?, ?, ?, ?, ?)', [(year, *p) for p in profiles])
            cursor.execute('INSERT OR REPLACE INTO duck_records VALUES (?, ?, ?, ?, ?, ?, ?)',
                           (year, best[0] * 100, *best[1:], over) if best else (year, None, None, None, None, None, over))
        cursor.execute(MARKET_INDEX_TABLE)
        cursor.executemany('INSERT OR REPLACE INTO market_index_hh VALUES (?, ?, ?, ?, ?, ?)', midp_history)
        for table in FORECAST_TABLES:
            cursor.execute(table)
        # Import and export arrive separately, so a missing one never wipes a stored rate
        cursor.executemany('''INSERT INTO agile_rates VALUES (?, ?, ?, ?) ON CONFLICT(valid_from) DO UPDATE SET
            valid_to = excluded.valid_to, import_p = COALESCE(excluded.import_p, import_p), export_p = COALESCE(excluded.export_p, export_p)''',
            forecasts.get('agile', []))
        cursor.executemany('''INSERT INTO carbon_forecast VALUES (?, ?, ?, ?) ON CONFLICT(period_from) DO UPDATE SET
            forecast = excluded.forecast, actual = COALESCE(excluded.actual, actual), index_label = excluded.index_label''',
            forecasts.get('carbon', []))
        cursor.executemany('INSERT OR REPLACE INTO generation_forecast VALUES (?, ?, ?, ?)', forecasts.get('generation', []))
        # Log attempts as well as successes, so a failing source is retried after its interval rather than every run
        cursor.executemany('INSERT OR REPLACE INTO fetch_log VALUES (?, ?)', [(name, now_utc.isoformat()) for name in neso_demand['attempted'] + forecasts['attempted'] + forecasts.get('done', []) + midp_done])
        save_health(cursor, now_utc, started)
        conn.commit()
        conn.close()
        print(f"-> Success! Row added.")
        check_alerts(now_utc)

    except Exception as e:
        print(f"-> Harvester Error: {e}")


if __name__ == '__main__':
    trim_log()
    fetch_and_store()