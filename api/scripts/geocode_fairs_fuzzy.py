import os
import time
import requests
import re
import mysql.connector

def get_town(name):
    # Remove common fair terms to isolate the town/county name
    clean = re.sub(r'(?i)\b(fair|farm show|grange|ag & youth|ag expo|community|county|state|youth|encampment|agricultural|society|inc|farmers|festival|show|2)\b', '', name)
    clean = clean.replace("&", "").replace("-", " ").replace("The ", "").replace("/", " ").strip()
    return re.sub(r'\s+', ' ', clean)

def main():
    db_pass = os.popen("grep DB_PASSWORD /mollie/.env | cut -d '=' -f2").read().strip().strip("'").strip('"')
    conn = mysql.connector.connect(host="localhost", port=3308, database="mollies_guide", user="mollies", password=db_pass)
    cur = conn.cursor(dictionary=True)

    cur.execute("SELECT id, name FROM locations WHERE category_id = 4 AND lat IS NULL")
    fairs = cur.fetchall()

    print(f"Found {len(fairs)} fairs still needing coordinates. Initiating fuzzy search...")
    headers = {'User-Agent': 'MolliesGuideApp/2.0 (Mapping PA Fairs Fuzzy)'}
    success = 0

    for fair in fairs:
        name = fair['name']
        town = get_town(name)
        
        # Try finding the fairgrounds, if that fails, just map the town itself
        queries = [
            f"{town} Fairgrounds, Pennsylvania",
            f"{town}, Pennsylvania"
        ]
        
        mapped = False
        for q in queries:
            url = f"https://nominatim.openstreetmap.org/search?q={requests.utils.quote(q)}&format=json&limit=1"
            try:
                res = requests.get(url, headers=headers, timeout=10).json()
                if res:
                    lat = res[0]['lat']
                    lng = res[0]['lon']
                    
                    update_cur = conn.cursor()
                    update_cur.execute("UPDATE locations SET lat = %s, lng = %s WHERE id = %s", (lat, lng, fair['id']))
                    conn.commit()
                    update_cur.close()
                    
                    print(f"✓ Mapped {name} via '{q}': {lat}, {lng}")
                    mapped = True
                    success += 1
                    time.sleep(1) # Be nice to the API
                    break
            except Exception:
                pass
            time.sleep(1.5)
        
        if not mapped:
            print(f"✗ Still could not pinpoint: {name} (Tried: {town})")

    cur.close()
    conn.close()
    print(f"\nFinished! Mapped {success} more fairs.")

if __name__ == "__main__":
    main()
