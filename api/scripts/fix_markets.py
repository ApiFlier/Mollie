import json
import os
import mysql.connector
from pathlib import Path

# Paths
ENV_FILE = Path("/mollie/.env")
DATA_FILE = Path("/mollie/api/data/mollie_markets.json")

def get_db_pass():
    with open(ENV_FILE) as f:
        for line in f:
            if "DB_PASSWORD" in line:
                return line.split("=")[1].strip().strip("'").strip('"')
    return None

def main():
    db_pass = get_db_pass()
    if not db_pass:
        print("Could not find DB_PASSWORD in .env")
        return

    with open(DATA_FILE) as f:
        data = json.load(f)

    # Handle different JSON structures
    locs = data.get("locations", data) if isinstance(data, dict) else data

    conn = mysql.connector.connect(
        host="localhost",
        port=3308,
        database="mollies_guide",
        user="mollies",
        password=db_pass
    )
    cur = conn.cursor()

    updated = 0
    for loc in locs:
        name = loc.get("name")
        # Grab date/hours/description
        date_info = loc.get("date") or loc.get("hours") or loc.get("description")
        
        if name and date_info:
            # We use Category 3 for Farmers Markets
            sql = "UPDATE locations SET notes = %s WHERE name = %s AND category_id = 3"
            cur.execute(sql, (date_info, name))
            if cur.rowcount > 0:
                updated += 1

    conn.commit()
    cur.close()
    conn.close()
    print(f"Successfully updated {updated} Farmers Markets with notes.")

if __name__ == "__main__":
    main()
