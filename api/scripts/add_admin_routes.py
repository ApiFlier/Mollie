import os
path = '/mollie/api/app.py'
with open(path, 'r') as f:
    code = f.read()

# This route handles updating the location details including our new fields
admin_route = """
@app.route("/locations/<int:loc_id>", methods=["PUT"])
def update_location(loc_id):
    data = request.get_json() or {}
    conn = get_conn()
    try:
        cur = conn.cursor()
        sql = \"\"\"
            UPDATE locations SET 
            name = %s, address = %s, city = %s, zip = %s, phone = %s, 
            website = %s, hours = %s, notes = %s, category_id = %s,
            event_date = %s, county = %s, 
            season_start_month = %s, season_end_month = %s
            WHERE id = %s
        \"\"\"
        params = (
            data.get('name'), data.get('address'), data.get('city'), data.get('zip'), 
            data.get('phone'), data.get('website'), data.get('hours'), data.get('notes'),
            data.get('category_id'), data.get('event_date'), data.get('county'),
            data.get('season_start_month'), data.get('season_end_month'), loc_id
        )
        cur.execute(sql, params)
        conn.commit()
        cur.close()
        return jsonify({"ok": True})
    finally:
        conn.close()

if __name__ == "__main__":
"""

if "def update_location" not in code:
    code = code.replace('if __name__ == "__main__":', admin_route.strip() + '\n')
    with open(path, 'w') as f:
        f.write(code)
        print("Admin update route successfully added!")
