"""The data sources on the Status page and how their state is worked out.

Shared by app.py (the Status page) and harvester.py (ntfy alerts), so both always agree.
"""
from datetime import datetime

# Grouped as on the page: (key the harvester reports under, name, what it is, how often it's fetched in minutes)
SOURCES = [
    ("Harvester", [
        ("internet", "Internet connection", "Checked at the start of every run", 5),
    ]),
    ("Grid: Elexon", [
        ("fuelinst", "Generation mix", "Output by fuel type and interconnector flows (FUELINST)", 5),
        ("itsdo", "Demand", "Transmission system demand (ITSDO)", 5),
        ("frequency", "Frequency", "Every 15-second reading", 5),
        ("system_prices", "Balancing price", "System sell price and imbalance volume", 5),
        ("market_index", "Market index price", "MIDP (EPEX SPOT)", 5),
        ("batteries", "Grid batteries", "Physical Notifications and Bid-Offer Acceptances", 5),
    ]),
    ("Grid: solar, wind & carbon", [
        ("pvlive", "Solar", "National solar estimate (PV_Live, Sheffield Solar)", 5),
        ("lv_wind", "Small embedded wind", "NESO embedded wind forecast", 5),
        ("carbon", "Carbon intensity", "NESO Carbon Intensity API, current half-hour", 5),
        ("carbon_forecast", "Carbon forecast", "NESO Carbon Intensity API, next 48 hours", 30),
        ("neso_demand", "Half-hourly demand", "NESO Demand Data Update (When Demand Shifts)", 180),
        ("neso_history", "Historic demand", "NESO Historic Demand Data (Duck Curve)", 1440),
    ]),
    ("Gas: National Gas", [
        ("gas", "Gas flows", "Linepack, supply and demand", 5),
        ("gas_storage", "Gas storage", "Daily storage and LNG stock levels", 5),
    ]),
    ("Home", [
        ("powerwall", "Powerwall", "Tesla gateway on the home network", 5),
        ("octopus_rates", "Agile rate now", "Octopus import and export rates for this half-hour", 5),
        ("agile_forecast", "Agile prices ahead", "Octopus rates published for later today and tomorrow", 30),
        ("octopus_meters", "Smart meters", "Octopus daily import, export and gas readings", 5),
        ("weather", "Weather", "Open-Meteo current conditions and forecast", 5),
    ]),
    ("Site", [
        ("cloudflare", "Visitor stats", "Cloudflare analytics", 5),
    ]),
]

def parse_utc(text):
    """ISO time from the harvester ('...Z', sometimes without seconds) as an aware UTC datetime."""
    return datetime.fromisoformat(text.replace('Z', '+00:00'))

def source_state(row, every_min, now):
    """ok, warn (a failed try, or late) or fail (3 failures in a row, or nothing good for 12 intervals)."""
    if not row or not row['last_attempt']: return 'unknown'
    since_ok = (now - parse_utc(row['last_ok'])).total_seconds() / 60 if row['last_ok'] else None
    if since_ok is None or since_ok > every_min * 12 or row['fails'] >= 3: return 'fail'
    if row['fails'] or since_ok > every_min * 3: return 'warn'
    return 'ok'
