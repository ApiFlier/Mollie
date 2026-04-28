import mysql.connector
import os

db_pass = os.popen("grep DB_PASSWORD /mollie/.env | cut -d '=' -f2").read().strip().strip("'").strip('"')
conn = mysql.connector.connect(host="localhost", port=3308, database="mollies_guide", user="mollies", password=db_pass)
cur = conn.cursor(dictionary=True)

cur.execute("SELECT id, notes FROM locations WHERE notes LIKE 'Date:%'")
rows = cur.fetchall()

for row in rows:
    parts = row['notes'].split('|', 1)
    date_part = parts[0].replace('Date:', '').strip()
    # If there was more text after the '|', keep it in notes, otherwise clear notes
    remaining_notes = parts[1].strip() if len(parts) > 1 else ""
    
    cur.execute("UPDATE locations SET event_date = %s, notes = %s WHERE id = %s", (date_part, remaining_notes, row['id']))

conn.commit()
print(f"Migrated {len(rows)} dates to the new event_date column.")
cur.close()
conn.close()
