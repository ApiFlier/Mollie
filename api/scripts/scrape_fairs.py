import os
import time
import requests
from bs4 import BeautifulSoup
import mysql.connector

def main():
    # Connect to Database
    db_pass = os.popen("grep DB_PASSWORD /mollie/.env | cut -d '=' -f2").read().strip().strip("'").strip('"')
    conn = mysql.connector.connect(host="localhost", port=3308, database="mollies_guide", user="mollies", password=db_pass)
    cur = conn.cursor()

    # Parse the Local HTML
    with open('/mollie/api/data/pafairs.html', 'r', encoding='utf-8') as f:
        soup = BeautifulSoup(f, 'html.parser')

    fairs = {}
    day_containers = soup.find_all('div', class_='dayContainer')
    
    for day in day_containers:
        date_val = day.get('date') # Format: 06/15/2026
        if not date_val: continue
        
        # Get all fair links inside this specific day
        links = day.find_all('a')
        for link in links:
            href = link.get('href', '')
            if 'events/' not in href: continue
            
            b_tag = link.find('b')
            if not b_tag: continue
            name = b_tag.text.strip()
            
            # Auto-stretch the schedule based on first and last appearance
            if href not in fairs:
                fairs[href] = {
                    'name': name,
                    'start_date': date_val,
                    'end_date': date_val,
                    'month': int(date_val.split('/')[0])
                }
            else:
                fairs[href]['end_date'] = date_val

    print(f"Found {len(fairs)} unique fairs! Beginning deep scrape...\n")

    # Visit each detail page to extract the official website
    headers = {'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64)'}
    
    for url, data in fairs.items():
        print(f"Scraping: {data['name']}...")
        website = ""
        
        try:
            res = requests.get(url, headers=headers, timeout=10)
            detail_soup = BeautifulSoup(res.text, 'html.parser')
            
            # Look for an external link that isn't facebook or the pafairs site
            for a in detail_soup.find_all('a', href=True):
                href_lower = a['href'].lower()
                if href_lower.startswith('http') and 'pafairs.org' not in href_lower and 'facebook.com' not in href_lower:
                    website = a['href']
                    break
            
            # Format the event date text
            if data['start_date'] != data['end_date']:
                event_date_text = f"{data['start_date']} to {data['end_date']}"
            else:
                event_date_text = data['start_date']

            # Insert into database (Category 4 = Festivals)
            cur.execute("""
                INSERT INTO locations (name, category_id, website, event_date, season_start_month, season_end_month) 
                VALUES (%s, 4, %s, %s, %s, %s)
            """, (data['name'], website, event_date_text, data['month'], data['month']))
            
        except Exception as e:
            print(f"  -> Error getting details: {e}")
            
        time.sleep(1)

    conn.commit()
    cur.close()
    conn.close()
    print("\nSuccessfully injected all fairs into the database!")

if __name__ == "__main__":
    main()
