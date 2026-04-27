import json
import os
import subprocess

with open("/mollie/api/data/mollie6.json") as f:
    data = json.load(f)

# Handle both flat lists and {locations: []} formats
locs = data.get("locations", data) if isinstance(data, dict) else data

sql_commands = []
for loc in locs:
    name = loc.get("name")
    # Grab whatever date/hour info is available
    date_info = loc.get("date") or loc.get("hours") or loc.get("description")
    
    if name and date_info:
        # Escape single quotes for SQL
        safe_name = name.replace("'", "''")
        safe_info = date_info.replace("'", "''")
        sql_commands.append(f"UPDATE locations SET notes = '{safe_info}' WHERE name = '{safe_name}' AND category_id = 3;")

if sql_commands:
    # Join commands and pipe to docker
    full_sql = "\n".join(sql_commands)
    password = subprocess.check_output("grep DB_PASSWORD /mollie/.env | cut -d '=' -f2", shell=True).decode().strip()
    cmd = f"docker exec -i mollies-db mysql -u mollies -p'{password}' mollies_guide"
    process = subprocess.Popen(cmd, shell=True, stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
    stdout, stderr = process.communicate(input=full_sql.encode())
    print("Market patch complete.")
else:
    print("No market data found to patch.")
