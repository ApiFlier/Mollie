import os
import time
import urllib.request
import urllib.parse
import json
import mysql.connector

def geocode(address_str):
    url = "https://nominatim.openstreetmap.org/search?" + urllib.parse.urlencode({
        'q': address_str,
        'format': 'json',
        'limit': 1
    })
    # Nominatim requires a custom User-Agent
    req = urllib.request.Request(url, headers={'User-Agent': 'MolliesGuideApp/1.0 (mollies_admin@local)'})
    try:
        with urllib.request.urlopen(req) as response:
            data = json.loads(response.read().decode())
            if data:
                return float(data[0]['lat']), float(data[0]['lon'])
    except Exception as e:
        print(f"  [!] Error fetching: {e}")
    return None, None

def main():
    # Connect to the database
    db_pass = os.popen("grep DB_PASSWORD /mollie/.env | cut -d '=' -f2").read().strip().strip("'").strip('"')
    conn = mysql.connector.connect(host="localhost", port=3308, database="mollies_guide", user="mollies", password=db_pass)
    cur = conn.cursor(dictionary=True)

    # Grab everything that is missing coordinates or set to 0.0
    cur.execute("SELECT id, name, address, city, state, zip FROM locations WHERE lat IS NULL OR lng IS NULL OR (lat = 0 AND lng = 0)")
    locations = cur.fetchall()

    print(f"📍 Found {len(locations)} locations needing coordinates. Starting geocoding...")
    print("⏳ Note: This will take about 1 second per location to respect API limits.\n")

    updated = 0
    for loc in locations:
        # Build the best search string possible
        parts = [loc['address'], loc['city'], loc['state'], loc['zip']]
        valid_parts = [str(p).strip() for p in parts if p and str(p).strip()]
        
        if not valid_parts:
            print(f"⏭️  Skipping {loc['name']} - no address data available.")
            continue
            
        search_str = ", ".join(valid_parts)
        print(f"🔍 Searching: {loc['name']} ({search_str})")
        
        lat, lng = geocode(search_str)
        
        # Smart Fallback: If full address fails, try just City and State
        if lat is None and loc['city'] and loc['state']:
            backup_str = f"{loc['city']}, {loc['state']}"
            print(f"  ⚠️  Street address failed. Retrying with City/State: {backup_str}")
            time.sleep(1.1) 
            lat, lng = geocode(backup_str)

        if lat is not None and lng is not None:
            update_cur = conn.cursor()
            update_cur.execute("UPDATE locations SET lat = %s, lng = %s WHERE id = %s", (lat, lng, loc['id']))
            conn.commit()
            update_cur.close()
            updated += 1
            print(f"  ✅ Success: {lat}, {lng}")
        else:
            print(f"  ❌ Could not find coordinates. Will need manual entry later.")
        
        # Mandatory delay for the free API
        time.sleep(1.1) 

    cur.close()
    conn.close()
    print(f"\n🎉 Done! Successfully mapped {updated} out of {len(locations)} locations.")

if __name__ == '__main__':
    main()
