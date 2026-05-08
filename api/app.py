import os
import bcrypt
from flask import Flask, jsonify, request, session, send_from_directory
from flask_cors import CORS
import mysql.connector
from mysql.connector import pooling

app = Flask(__name__, static_url_path='', static_folder='static')
app.secret_key = os.environ.get("FLASK_SECRET") or os.urandom(32)

app.config.update(
    SESSION_COOKIE_NAME="event_map_session",
    SESSION_COOKIE_HTTPONLY=True,
    SESSION_COOKIE_SAMESITE="Lax",
    SESSION_COOKIE_SECURE=False,
    PERMANENT_SESSION_LIFETIME=60 * 60 * 24
)
CORS(app, supports_credentials=True)

HTPASSWD_FILE = "/app/.htpasswd"

DB_CONFIG = {
    "host": os.environ.get("DB_HOST", "db"),
    "database": os.environ.get("DB_NAME", "event_map"),
    "user": os.environ.get("DB_USER", "event_map"),
    "password": os.environ.get("DB_PASSWORD", ""),
    "pool_name": "event_map_pool",
    "pool_size": 15,
}

_pool = None
def get_conn():
    global _pool
    if _pool is None: _pool = pooling.MySQLConnectionPool(**DB_CONFIG)
    return _pool.get_connection()

def _read_htpasswd():
    if not os.path.exists(HTPASSWD_FILE):
        return {}
    users = {}
    with open(HTPASSWD_FILE, "r") as f:
        for line in f:
            line = line.strip()
            if ":" in line:
                u, h = line.split(":", 1)
                users[u] = h
    return users

def _check_password(stored_hash, password):
    if stored_hash.startswith("$2y$"):
        stored_hash = "$2b$" + stored_hash[4:]
    try:
        return bcrypt.checkpw(password.encode(), stored_hash.encode())
    except Exception:
        return False

def _require_auth():
    if not session.get("authenticated"):
        return jsonify({"error": "Not authenticated"}), 401
    return None

@app.route("/health")
@app.route("/api/health")
def health():
    return jsonify({"status": "ok", "ok": True})

@app.route("/login", methods=["POST"])
@app.route("/api/login", methods=["POST"])
def login():
    data = request.get_json() or {}
    username = data.get("username", "")
    password = data.get("password", "")
    users = _read_htpasswd()
    if not users:
        return jsonify({"error": "Auth not configured"}), 500
    stored = users.get(username)
    if not stored or not _check_password(stored, password):
        return jsonify({"error": "Invalid credentials"}), 401
    session.permanent = True
    session["authenticated"] = True
    session["username"] = username
    return jsonify({"ok": True})

@app.route("/logout", methods=["POST"])
@app.route("/api/logout", methods=["POST"])
def logout():
    session.clear()
    return jsonify({"ok": True})

@app.route("/auth-check")
@app.route("/api/auth-check")
@app.route("/auth/check")
@app.route("/api/auth/check")
@app.route("/status")
@app.route("/api/status")
@app.route("/verify")
@app.route("/api/verify")
def auth_check():
    if session.get("authenticated"):
        return jsonify({"authenticated": True, "ok": True, "status": "logged_in"})
    return jsonify({"authenticated": False, "ok": False}), 401

@app.route("/credentials")
@app.route("/api/credentials")
def get_credentials():
    err = _require_auth()
    if err: return err
    users = _read_htpasswd()
    username = list(users.keys())[0] if users else ""
    return jsonify({"username": username})

@app.route("/credentials", methods=["PUT"])
@app.route("/api/credentials", methods=["PUT"])
def update_credentials():
    err = _require_auth()
    if err: return err
    data = request.get_json() or {}
    current_password = data.get("current_password", "")
    new_username = data.get("new_username")
    new_password = data.get("new_password")

    users = _read_htpasswd()
    current_username = session.get("username", list(users.keys())[0] if users else "")
    stored = users.get(current_username)
    if not stored or not _check_password(stored, current_password):
        return jsonify({"error": "Current password is incorrect"}), 401

    target_username = new_username or current_username
    if new_password:
        new_hash = bcrypt.hashpw(new_password.encode(), bcrypt.gensalt()).decode()
    else:
        new_hash = stored

    try:
        with open(HTPASSWD_FILE, "w") as f:
            f.write(f"{target_username}:{new_hash}\n")
    except OSError as e:
        return jsonify({"error": f"Could not write credentials: {e}"}), 500

    session["username"] = target_username
    return jsonify({"ok": True})

@app.route("/categories")
@app.route("/api/categories")
def get_categories():
    conn = get_conn()
    try:
        cur = conn.cursor(dictionary=True)
        cur.execute("SELECT * FROM categories ORDER BY id")
        res = cur.fetchall()
        cur.close()
        return jsonify(res)
    finally:
        conn.close()

@app.route("/crops/distinct")
@app.route("/api/crops/distinct")
def get_distinct_crops():
    conn = get_conn()
    try:
        cur = conn.cursor(dictionary=True)
        cur.execute("SELECT name, COUNT(DISTINCT location_id) as farm_count FROM crops GROUP BY name ORDER BY name")
        res = cur.fetchall()
        cur.close()
        return jsonify(res)
    finally:
        conn.close()

@app.route("/locations")
@app.route("/api/locations")
def get_locations():
    cat = request.args.get("category")
    month = request.args.get("month", type=int)
    crop = request.args.get("crop", "").strip().lower()
    conn = get_conn()
    try:
        cur = conn.cursor(dictionary=True)
        where, params = [], []
        if cat:
            cats = [c.strip() for c in cat.split(",")]
            where.append(f"c.name IN ({','.join(['%s']*len(cats))})")
            params.extend(cats)
        if month:
            loc_m = "(%s BETWEEN l.season_start_month AND l.season_end_month OR (l.season_start_month > l.season_end_month AND (%s >= l.season_start_month OR %s <= l.season_end_month)))"
            crop_m = "EXISTS (SELECT 1 FROM crops cr WHERE cr.location_id = l.id AND (%s BETWEEN cr.season_start_month AND cr.season_end_month OR (cr.season_start_month > cr.season_end_month AND (%s >= cr.season_start_month OR %s <= cr.season_end_month))))"
            where.append(f"({loc_m} OR {crop_m})")
            params.extend([month]*6)
        if crop:
            where.append("(EXISTS (SELECT 1 FROM crops cr WHERE cr.location_id = l.id AND LOWER(cr.name) LIKE %s) OR l.county = %s)")
            params.extend([f"%{crop}%", crop])
        wc = " WHERE " + " AND ".join(where) if where else ""
        sql = f"SELECT l.*, c.name AS category, c.color AS category_color FROM locations l LEFT JOIN categories c ON l.category_id = c.id {wc}"
        cur.execute(sql, params)
        res = cur.fetchall()
        cur.close()
        return jsonify(res)
    finally:
        conn.close()

@app.route("/locations/<int:loc_id>", methods=["GET"])
@app.route("/api/locations/<int:loc_id>", methods=["GET"])
def get_location(loc_id):
    conn = get_conn()
    try:
        cur = conn.cursor(dictionary=True)
        cur.execute("SELECT l.*, c.name AS category FROM locations l LEFT JOIN categories c ON l.category_id = c.id WHERE l.id = %s", (loc_id,))
        loc = cur.fetchone()
        if loc:
            cur.execute("SELECT * FROM crops WHERE location_id = %s", (loc_id,))
            loc["crops"] = cur.fetchall()
        cur.close()
        return jsonify(loc)
    finally:
        conn.close()

@app.route("/locations/<int:loc_id>", methods=["PUT"])
@app.route("/api/locations/<int:loc_id>", methods=["PUT"])
def update_location(loc_id):
    data = request.get_json() or {}
    conn = get_conn()
    try:
        cur = conn.cursor()
        sql = """
            UPDATE locations SET
            name = %s, address = %s, city = %s, zip = %s, phone = %s,
            website = %s, hours = %s, notes = %s, category_id = %s,
            event_date = %s, county = %s,
            season_start_month = %s, season_end_month = %s
            WHERE id = %s
        """
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

@app.route("/locations/<int:loc_id>/notes", methods=["GET"])
@app.route("/api/locations/<int:loc_id>/notes", methods=["GET"])
def get_notes(loc_id):
    conn = get_conn()
    try:
        cur = conn.cursor(dictionary=True)
        cur.execute("SELECT * FROM notes WHERE location_id = %s ORDER BY created_at DESC", (loc_id,))
        res = cur.fetchall()
        cur.close()
        return jsonify(res)
    finally:
        conn.close()

@app.route("/locations/<int:loc_id>/notes", methods=["POST"])
@app.route("/api/locations/<int:loc_id>/notes", methods=["POST"])
def add_note(loc_id):
    data = request.get_json() or {}
    note = data.get("note", "").strip()
    if not note: return jsonify({"error": "empty note"}), 400
    conn = get_conn()
    try:
        cur = conn.cursor()
        cur.execute("INSERT INTO notes (location_id, note) VALUES (%s, %s)", (loc_id, note))
        conn.commit()
        cur.close()
        return jsonify({"ok": True})
    finally:
        conn.close()

@app.route("/locations/<int:loc_id>/notes/<int:note_id>", methods=["DELETE"])
@app.route("/api/locations/<int:loc_id>/notes/<int:note_id>", methods=["DELETE"])
def delete_note(loc_id, note_id):
    conn = get_conn()
    try:
        cur = conn.cursor()
        cur.execute("DELETE FROM notes WHERE id = %s AND location_id = %s", (note_id, loc_id))
        conn.commit()
        cur.close()
        return jsonify({"ok": True})
    finally:
        conn.close()

@app.route("/counties")
@app.route("/api/counties")
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
@app.route("/api/locations", methods=["POST"])
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
@app.route("/api/locations/<int:loc_id>", methods=["DELETE"])
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
@app.route("/api/locations/<int:loc_id>/crops", methods=["POST"])
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
@app.route("/api/crops/<int:crop_id>", methods=["PUT"])
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
@app.route("/api/crops/<int:crop_id>", methods=["DELETE"])
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

@app.route("/")
def index():
    return app.send_static_file("index.html")

@app.route("/admin/")
def admin_index():
    return app.send_static_file("admin/index.html")

if __name__ == "__main__":
    app.run(host="0.0.0.0", port=8080)
