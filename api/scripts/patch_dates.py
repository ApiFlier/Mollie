import json
import os
import mysql.connector
from pathlib import Path

DATA_FILE = Path("/mollie/api/data/mollie_festivals.json")
DB_CONFIG = {
    "host": "localhost",
    "port": 3308,
    "database": "mollies_guide",
    "user": "mollies",
    "password": os.environ.get("DB_PASSWORD"),
}

def main():
    if not DATA_FILE.exists():
        print("Festival JSON not found.")
        return

    with open(DATA_FILE) as f:
        festivals = json.load(f)

    conn = mysql.connector.connect(**DB_CONFIG)
    cur = conn.cursor()

    updated = 0
    for fest in festivals:
        name = fest.get("name")
        date_info = fest.get("date")
        
        if name and date_info:
            # We update the 'notes' column with the 'date' value from JSON
            sql = "UPDATE locations SET notes = %s WHERE name = %s AND (notes IS NULL OR notes = '')"
            cur.execute(sql, (f"Date: {date_info}", name))
            if cur.rowcount > 0:
                updated += 1

    conn.commit()
    print(f"Successfully patched {updated} festival dates into the database.")
    cur.close()
    conn.close()

if __name__ == "__main__":
    main()
