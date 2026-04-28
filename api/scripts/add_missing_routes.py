import os
path = '/mollie/api/app.py'
with open(path, 'r') as f:
    code = f.read()

missing_routes = """
@app.route("/counties")
def get_counties():
    conn = get_conn()
    try:
        cur = conn.cursor()
        cur.execute("SELECT DISTINCT county FROM locations WHERE county IS NOT NULL AND county != '' ORDER BY county")
        res = [r[0] for r in cur.fetchall()]
        cur.close()
        return jsonify(res)
    finally:
        conn.close()

@app.route("/locations", methods=["POST"])
def create_location():
    data = request.get_json() or {}
    conn = get_conn()
    try:
        cur = conn.cursor()
        sql = '''
            INSERT INTO locations (name, address, city, zip, phone, website, hours, notes, category_id, event_date, county, season_start_month, season_end_month)
            VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
        '''
        params = (
            data.get('name'), data.get('address'), data.get('city'), data.get('zip'), 
            data.get('phone'), data.get('website'), data.get('hours'), data.get('notes'),
            data.get('category_id'), data.get('event_date'), data.get('county'),
            data.get('season_start_month'), data.get('season_end_month')
        )
        cur.execute(sql, params)
        new_id = cur.lastrowid
        conn.commit()
        cur.close()
        return jsonify({"ok": True, "id": new_id})
    finally:
        conn.close()

@app.route("/locations/<int:loc_id>", methods=["DELETE"])
def delete_location(loc_id):
    conn = get_conn()
    try:
        cur = conn.cursor()
        cur.execute("DELETE FROM locations WHERE id = %s", (loc_id,))
        conn.commit()
        cur.close()
        return jsonify({"ok": True})
    finally:
        conn.close()

@app.route("/locations/<int:loc_id>/crops", methods=["POST"])
def add_loc_crop(loc_id):
    data = request.get_json() or {}
    conn = get_conn()
    try:
        cur = conn.cursor()
        cur.execute("INSERT INTO crops (location_id, name, is_pyo, season_start_month, season_end_month) VALUES (%s, %s, %s, %s, %s)",
            (loc_id, data.get('name'), data.get('is_pyo'), data.get('season_start_month'), data.get('season_end_month')))
        conn.commit()
        cur.close()
        return jsonify({"ok": True})
    finally:
        conn.close()

@app.route("/crops/<int:crop_id>", methods=["PUT"])
def update_loc_crop(crop_id):
    data = request.get_json() or {}
    conn = get_conn()
    try:
        cur = conn.cursor()
        cur.execute("UPDATE crops SET name=%s, is_pyo=%s, season_start_month=%s, season_end_month=%s WHERE id=%s",
            (data.get('name'), data.get('is_pyo'), data.get('season_start_month'), data.get('season_end_month'), crop_id))
        conn.commit()
        cur.close()
        return jsonify({"ok": True})
    finally:
        conn.close()

@app.route("/crops/<int:crop_id>", methods=["DELETE"])
def delete_loc_crop(crop_id):
    conn = get_conn()
    try:
        cur = conn.cursor()
        cur.execute("DELETE FROM crops WHERE id = %s", (crop_id,))
        conn.commit()
        cur.close()
        return jsonify({"ok": True})
    finally:
        conn.close()
"""

if 'def get_counties' not in code:
    code = code.replace('if __name__ == "__main__":', missing_routes.strip() + '\n\nif __name__ == "__main__":')
    with open(path, 'w') as f:
        f.write(code)
    print("Missing routes patched successfully!")
