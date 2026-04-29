import os
import json
import mysql.connector

def main():
    # 1. Connect to the database
    db_pass = os.popen("grep DB_PASSWORD /mollie/.env | cut -d '=' -f2").read().strip().strip("'").strip('"')
    conn = mysql.connector.connect(host="localhost", port=3308, database="mollies_guide", user="mollies", password=db_pass)
    cur = conn.cursor(dictionary=True)

    # 2. Load the JSON Data
    json_path = '/mollie/api/data/mollie_farms.json'
    with open(json_path, 'r') as f:
        data = json.load(f)

    # 3. Get Category IDs mapping
    cur.execute("SELECT id, name FROM categories")
    cats = {r['name']: r['id'] for r in cur.fetchall()}

    # Ensure categories exist
    for req_cat in ['farm']:
        if req_cat not in cats:
            cur.execute("INSERT INTO categories (name, color) VALUES (%s, '#4CAF50')", (req_cat,))
            cats[req_cat] = cur.lastrowid

    # 4. Find and completely wipe old farm/pyo data
    cat_ids = [cats['farm']]
    format_strings = ','.join(['%s'] * len(cat_ids))
    cur.execute(f"SELECT id FROM locations WHERE category_id IN ({format_strings})", tuple(cat_ids))
    loc_ids = [r['id'] for r in cur.fetchall()]

    if loc_ids:
        loc_format = ','.join(['%s'] * len(loc_ids))
        # Cascading deletes to ensure no orphan crops or private notes are left behind
        cur.execute(f"DELETE FROM crops WHERE location_id IN ({loc_format})", tuple(loc_ids))
        cur.execute(f"DELETE FROM notes WHERE location_id IN ({loc_format})", tuple(loc_ids))
        cur.execute(f"DELETE FROM locations WHERE id IN ({loc_format})", tuple(loc_ids))
        print(f"🧹 Cleaned up {len(loc_ids)} old farm locations.")

    # 5. Dynamically check valid columns in the database to prevent crashes
    cur.execute("SHOW COLUMNS FROM locations")
    valid_columns = [r['Field'] for r in cur.fetchall()]

    # 6. Insert new locations
    inserted_count = 0
    for loc in data.get('locations', []):
        loc_data = {}
        for key, val in loc.items():
            if key == 'crops':
                continue
            if key == 'category':
                loc_data['category_id'] = cats.get(val, cats['farm'])
                continue
            if key in valid_columns:
                # Handle lists (like amenities) if your DB supports JSON, otherwise gracefully serialize
                if isinstance(val, list):
                    loc_data[key] = json.dumps(val)
                elif isinstance(val, bool):
                    loc_data[key] = 1 if val else 0
                else:
                    loc_data[key] = val

        cols = list(loc_data.keys())
        vals = list(loc_data.values())
        placeholders = ', '.join(['%s'] * len(cols))
        col_names = ', '.join(cols)

        sql = f"INSERT INTO locations ({col_names}) VALUES ({placeholders})"
        cur.execute(sql, tuple(vals))
        new_loc_id = cur.lastrowid
        inserted_count += 1

        # Insert crops for this farm
        crops = loc.get('crops', [])
        for crop in crops:
            cur.execute(
                "INSERT INTO crops (location_id, name, is_pyo, season_start_month, season_end_month) VALUES (%s, %s, %s, %s, %s)",
                (new_loc_id, crop.get('name'), crop.get('is_pyo', False), crop.get('season_start_month'), crop.get('season_end_month'))
            )

    conn.commit()
    cur.close()
    conn.close()
    print(f"✅ Successfully imported {inserted_count} clean farms and pick-your-owns from JSON!")

if __name__ == "__main__":
    main()
