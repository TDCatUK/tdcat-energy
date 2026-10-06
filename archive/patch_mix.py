import sqlite3
import json
import shutil
from datetime import datetime

db_file = 'grid_data.db'

# 1. Create a timestamped backup first!
now_str = datetime.now().strftime('%Y%m%d_%H%M%S')
backup_file = f'grid_data_backup_mix_{now_str}.db'

try:
    shutil.copy2(db_file, backup_file)
    print(f"-> Backup created successfully: {backup_file}")
except Exception as e:
    print(f"-> Error creating backup: {e}")
    exit(1)

# 2. Connect to the database
conn = sqlite3.connect(db_file)
cursor = conn.cursor()

cursor.execute("SELECT timestamp, generation_mix, total_generation_mw FROM energy_snapshots ORDER BY timestamp ASC")
rows = cursor.fetchall()

updates = []
last_good_mix = None

for row in rows:
    ts = row[0]
    mix_str = row[1]
    gen_mw = row[2]

    try:
        mix = json.loads(mix_str) if mix_str else {}
    except:
        mix = {}

    # Check the Elexon portion of the mix (everything except Solar and LV Wind)
    elexon_total = sum(v for k, v in mix.items() if k not in ['Solar', 'LV Wind'])

    if elexon_total > 15000:
        # This is a healthy mix! Save it as our fallback template.
        last_good_mix = mix.copy()
        
    elif elexon_total < 15000 and last_good_mix is not None:
        # Elexon timed out! We only have Solar/LV Wind here.
        # Let's rebuild the mix using the last known good Elexon data.
        rebuilt_mix = last_good_mix.copy()
        
        # Keep the current LV Wind and Solar if they exist
        if 'LV Wind' in mix:
            rebuilt_mix['LV Wind'] = mix['LV Wind']
        if 'Solar' in mix:
            rebuilt_mix['Solar'] = mix['Solar']
            
        new_mix_str = json.dumps(rebuilt_mix)
        
        # Re-calculate the true total generation just to be perfectly accurate
        new_total_gen = sum(rebuilt_mix.values())

        updates.append((new_mix_str, new_total_gen, ts))

# 3. Apply the updates
if updates:
    print(f"-> Found {len(updates)} rows with missing Elexon mix data. Patching...")
    cursor.executemany("UPDATE energy_snapshots SET generation_mix = ?, total_generation_mw = ? WHERE timestamp = ?", updates)
    conn.commit()
    print("-> Database patched successfully!")
else:
    print("-> No anomalies found.")

conn.close()