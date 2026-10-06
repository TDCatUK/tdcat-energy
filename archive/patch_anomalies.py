import sqlite3
import json
import shutil
from datetime import datetime

db_file = 'grid_data.db'

# 1. Create a timestamped backup first!
now_str = datetime.now().strftime('%Y%m%d_%H%M%S')
backup_file = f'grid_data_backup_anomalies_{now_str}.db'

try:
    shutil.copy2(db_file, backup_file)
    print(f"-> Backup created successfully: {backup_file}")
except Exception as e:
    print(f"-> Error creating backup: {e}")
    exit(1)

# 2. Connect to the database
conn = sqlite3.connect(db_file)
cursor = conn.cursor()

# The true value we successfully retrieved later that evening
TARGET_LV_MW = 3101 
# The specific glitch values we want to target
BAD_VALUES = [0, 1751, 6606]

# Grab only the rows from yesterday evening between 19:00 and 20:59
cursor.execute("""
    SELECT timestamp, embedded_wind_mw, generation_mix, demand_mw, total_generation_mw 
    FROM energy_snapshots 
    WHERE timestamp LIKE '2026-04-29T19:%' OR timestamp LIKE '2026-04-29T20:%'
""")
rows = cursor.fetchall()

updates = []

for row in rows:
    ts = row[0]
    old_lv_mw = row[1] if row[1] is not None else 0
    mix_str = row[2]
    old_demand = row[3] if row[3] is not None else 0
    old_gen = row[4] if row[4] is not None else 0

    if old_lv_mw in BAD_VALUES:
        try:
            mix = json.loads(mix_str) if mix_str else {}
        except:
            mix = {}

        # Calculate the mathematical difference to fix the Demand and Generation totals
        diff = TARGET_LV_MW - old_lv_mw
        
        new_demand = old_demand + diff
        new_gen = old_gen + diff
        
        # Inject the correct value into the JSON dictionary
        mix['LV Wind'] = TARGET_LV_MW
        new_mix_str = json.dumps(mix)

        updates.append((TARGET_LV_MW, new_mix_str, new_demand, new_gen, ts))

# 3. Apply the updates
if updates:
    print(f"-> Found {len(updates)} anomalous rows from yesterday evening. Patching...")
    cursor.executemany("""
        UPDATE energy_snapshots 
        SET embedded_wind_mw = ?, generation_mix = ?, demand_mw = ?, total_generation_mw = ? 
        WHERE timestamp = ?
    """, updates)
    conn.commit()
    print("-> Database anomalies patched successfully!")
else:
    print("-> No anomalies found for that timeframe.")

conn.close()