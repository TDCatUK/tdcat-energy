import sqlite3
import json

db_file = 'grid_data.db'
conn = sqlite3.connect(db_file)
cursor = conn.cursor()

# Fetch the relevant columns
cursor.execute("SELECT timestamp, embedded_wind_mw, generation_mix, demand_mw, total_generation_mw FROM energy_snapshots")
rows = cursor.fetchall()

updates = []

for row in rows:
    ts = row[0]
    lv_mw = row[1] if row[1] is not None else 0
    mix_str = row[2]
    demand = row[3] if row[3] is not None else 0
    gen = row[4] if row[4] is not None else 0

    if not mix_str:
        continue

    try:
        mix = json.loads(mix_str)
    except:
        continue

    # If we have a recovered LV Wind value, but it's missing from (or 0 in) the JSON mix
    if lv_mw > 0 and mix.get('LV Wind', 0) == 0:
        # 1. Inject it into the JSON mix
        mix['LV Wind'] = lv_mw
        new_mix_str = json.dumps(mix)
        
        # 2. Add it back to the totals so the lines match up
        new_demand = demand + lv_mw
        new_gen = gen + lv_mw
        
        updates.append((new_mix_str, new_demand, new_gen, ts))

if updates:
    print(f"-> Found {len(updates)} rows with missing JSON/Total data. Patching...")
    cursor.executemany(
        "UPDATE energy_snapshots SET generation_mix = ?, demand_mw = ?, total_generation_mw = ? WHERE timestamp = ?",
        updates
    )
    conn.commit()
    print("-> Database JSON and Totals patched successfully!")
else:
    print("-> No rows needed patching.")

conn.close()