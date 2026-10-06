import requests
from datetime import datetime, timedelta, timezone

# === GRID FREQUENCY API ===
ELEXON_FREQUENCY_URL_BASE = (
    "https://data.elexon.co.uk/bmrs/api/v1/system/frequency/stream"
)

try:
    # Build a rolling window: last 20 minutes (adjust as needed)
    now_utc = datetime.now(timezone.utc)
    from_dt = (now_utc - timedelta(minutes=20)).isoformat(
        timespec="seconds"
    )  # e.g. 2026-04-27T14:05:00+00:00

    # Optional: explicit ToDateTime (defaults to now if omitted)
    # to_dt = now_utc.isoformat(timespec='seconds')

    url = f"{ELEXON_FREQUENCY_URL_BASE}?FromDateTime={from_dt}"
    # If you want to be explicit: url = f"{ELEXON_FREQUENCY_URL_BASE}?FromDateTime={from_dt}&ToDateTime={to_dt}"

    freq_res = requests.get(url, timeout=req_timeout).json()

    # The stream endpoint returns a flat list (no 'data' wrapper in most cases)
    data_list = (
        freq_res
        if isinstance(freq_res, list)
        else freq_res.get("data", []) if isinstance(freq_res, dict) else []
    )

    if data_list:
        # Sort descending by measurementTime (guarantees absolute latest)
        data_list.sort(key=lambda x: x.get("measurementTime", ""), reverse=True)
        latest = data_list[0]
        grid_frequency = float(latest.get("frequency") or 50.0)

        # === RECOMMENDED: Log for debugging / verification ===
        print(
            f"✅ Latest frequency: {grid_frequency} Hz at {latest.get('measurementTime')}"
        )
        print(f"   (Fetched {len(data_list)} readings in the window)")
    else:
        grid_frequency = 50.0
        print("⚠️ No frequency data returned in the requested window")

except Exception as e:
    print(f"Frequency error: {e}")
    grid_frequency = 50.0
