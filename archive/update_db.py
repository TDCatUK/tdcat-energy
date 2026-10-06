import sqlite3

print("=== Cloudflare Column Migration Tool ===")
print("Connecting to grid_data.db...")

conn = sqlite3.connect('grid_data.db')
cursor = conn.cursor()

try:
    cursor.executescript('''
        ALTER TABLE energy_snapshots ADD COLUMN cf_visits_24h    INTEGER DEFAULT 0;
        ALTER TABLE energy_snapshots ADD COLUMN cf_requests_24h  INTEGER DEFAULT 0;
        ALTER TABLE energy_snapshots ADD COLUMN cf_bytes_24h     INTEGER DEFAULT 0;
    ''')
    conn.commit()
    print("✅ Success! The three Cloudflare columns have been added.")

except sqlite3.OperationalError as e:
    if "duplicate column name" in str(e).lower():
        print("✅ The columns already exist — nothing to do.")
    else:
        print(f"❌ Database error: {e}")
except Exception as e:
    print(f"❌ Unexpected error: {e}")
finally:
    conn.close()
    print("Migration tool finished.\n")

print("You can now safely run your updated harvester script!")