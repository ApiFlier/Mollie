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
        # Clean the name: take the first 15 chars to avoid "I" or "II" suffix issues
        short_name = name[:15] if name else ""
        date_info = fest.get("date")
        
        if short_name and date_info:
            # Use LIKE to match the start of the name
            sql = "UPDATE locations SET notes = %s WHERE name LIKE %s AND category_id = 4 AND (notes IS NULL OR notes = '')"
            cur.execute(sql, (f"Date: {date_info}", f"{short_name}%"))
            if cur.rowcount > 0:
                updated += cur.rowcount

    conn.commit()
    print(f"Fuzzy Match: Patched {updated} festival dates.")
    cur.close()
    conn.close()

if __name__ == "__main__":
    main()
