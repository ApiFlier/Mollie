import json
import os
import mysql.connector
from pathlib import Path

# Paths
ENV_FILE = Path("/mollie/.env")
FEST_JSON = Path("/mollie/api/data/mollie_festivals.json")

def get_db_pass():
    with open(ENV_FILE) as f:
        for line in f:
            if "DB_PASSWORD" in line:
                return line.split("=")[1].strip().strip("'").strip('"')
    return None

def main():
    db_pass = get_db_pass()
    conn = mysql.connector.connect(
        host="localhost", port=3308, database="mollies_guide",
        user="mollies", password=db_pass
    )
    cur = conn.cursor()

    # 1. Update Farmers Markets (Category 3) to May-Oct
    cur.execute("UPDATE locations SET season_start_month = 5, season_end_month = 10 WHERE category_id = 3")
    print(f"Updated {cur.rowcount} markets to May-Oct season.")

    # 2. Update Festivals (Category 4) from JSON
    with open(FEST_JSON) as f:
        festivals = json.load(f)
    
    fest_count = 0
    for fest in festivals:
        name = fest.get("name")
        date_str = fest.get("date", "")
        if name and "/" in date_str:
            month = date_str.split("/")[0]
            if month.isdigit():
                m_int = int(month)
                cur.execute(
                    "UPDATE locations SET season_start_month = %s, season_end_month = %s WHERE name = %s AND category_id = 4",
                    (m_int, m_int, name)
                )
                fest_count += cur.rowcount

    conn.commit()
    cur.close()
    conn.close()
    print(f"Updated {fest_count} festivals with specific months.")

if __name__ == "__main__":
    main()
