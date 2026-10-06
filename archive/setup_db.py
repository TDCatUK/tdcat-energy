import sqlite3

def create_database():
    conn = sqlite3.connect('grid_data.db')
    cursor = conn.cursor()
    
    # Create the table to hold our grid snapshots
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS energy_snapshots (
            timestamp DATETIME PRIMARY KEY,
            carbon_intensity REAL,
            demand_mw REAL,
            total_generation_mw REAL,
            net_flow_mw REAL,
            wholesale_price REAL,
            generation_mix TEXT,
            interconnector_flows TEXT
        )
    ''')
    
    conn.commit()
    conn.close()
    print("Database 'grid_data.db' created successfully on OTTO!")

if __name__ == '__main__':
    create_database()