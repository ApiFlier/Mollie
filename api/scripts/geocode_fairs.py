import os
import time
import requests
import mysql.connector

def main():
    db_pass = os.popen("grep DB_PASSWORD /mollie/.env | cut -d '=' -f2").read().strip().strip("'").strip('"')
    conn = mysql.connector.connect(host="localhost", port=3308, database="mollies_guide", user="mollies", password=db_pass)
    cur = conn.cursor(dictionary=True)

    # Find all fairs that don't have coordinates yet
    cur.execute("SELECT id, name FROM locations WHERE category_id = 4 AND lat IS NULL")
    fairs = cur.fetchall()

    print(f"Found {len(fairs)} fairs needing coordinates. Firing up the satellite...")

    # OpenStreetMap requires a custom User-Agent
    headers = {'User-Agent': 'MolliesGuideApp/1.0 (Mapping PA Fairs)'}
    success = 0

    for fair in fairs:
        # Some fairs have "2" or weird characters at the end from the scrape, clean it slightly for the search
        clean_name = fair['name'].replace(" 2", "").strip()
        query = f"{clean_name}, Pennsylvania"
        
        # Hit the free Nominatim API
        url = f"https://nominatim.openstreetmap.org/search?q={requests.utils.quote(query)}&format=json&limit=1"
        
        try:
            res = requests.get(url, headers=headers, timeout=10).json()
            if res:
                lat = res[0]['lat']
                lng = res[0]['lon']
                
                # Update the database
                update_cur = conn.cursor()
                update_cur.execute("UPDATE locations SET lat = %s, lng = %s WHERE id = %s", (lat, lng, fair['id']))
                conn.commit()
                update_cur.close()
                
                print(f"✓ Mapped {clean_name}: {lat}, {lng}")
                success += 1
            else:
                print(f"✗ Could not pinpoint: {clean_name}")
                
        except Exception as e:
            print(f"! Error finding {clean_name}: {e}")
            
        # OpenStreetMap is free, but requires we wait 1.5 seconds between searches
        time.sleep(1.5)

    cur.close()
    conn.close()
    print(f"\nFinished! Successfully mapped {success} out of {len(fairs)} fairs.")

if __name__ == "__main__":
    main()
