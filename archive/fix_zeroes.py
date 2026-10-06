import sqlite3
import shutil
from datetime import datetime

db_file = 'grid_data.db'

# 1. Create a timestamped backup
now_str = datetime.now().strftime('%Y%m%d_%H%M%S')
backup_file = f'grid_data_backup_{now_str}.db'

try:
    shutil.copy2(db_file, backup_file)
    print(f"-> Backup created successfully: {backup_file}")
except Exception as e:
    print(f"-> Error creating backup: {e}")
    exit(1)

# 2. Connect to the database
conn = sqlite3.connect(db_file)
cursor = conn.cursor()

# Fetch all timestamps and embedded wind values, ordered chronologically (oldest to newest)
cursor.execute("SELECT timestamp, embedded_wind_mw FROM energy_snapshots ORDER BY timestamp ASC")
rows = cursor.fetchall()

updates = []
last_valid_value = 0

for row in rows:
    timestamp = row[0]
    # Handle cases where the column might be NULL in older rows
    current_val = row[1] if row[1] is not None else 0

    if current_val > 0:
        # We found a real reading! Update our tracker.
        last_valid_value = current_val
    elif current_val == 0 and last_valid_value > 0:
        # We hit a zero, AND we've already seen valid data previously. Patch it!
        updates.append((last_valid_value, timestamp))

# 3. Apply the updates to the database
if updates:
    print(f"-> Found {len(updates)} zero-value rows since the feature was added. Patching...")
    cursor.executemany(
        "UPDATE energy_snapshots SET embedded_wind_mw = ? WHERE timestamp = ?",
        updates
    )
    conn.commit()
    print("-> Database patched successfully!")
else:
    print("-> No zero values found that needed patching.")

conn.close()
print("-> Done. Your charts should now be perfectly smooth.")