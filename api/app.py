import os
import json
import datetime
import bcrypt
import requests as http_requests
from flask import Flask, jsonify, request, session, send_from_directory
from flask_cors import CORS
import mysql.connector
from mysql.connector import pooling

import events as _events
from adapters.positively_pgh import PositivelyPgh
from adapters.visit_pittsburgh import VisitPittsburgh

_events.register_adapter(PositivelyPgh())
_events.register_adapter(VisitPittsburgh())

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

def _try_geocode(address, city, state, zip_code):
    """Geocode an address via Nominatim. Returns (lat, lng) or (None, None) on failure."""
    parts = [p for p in [address, city, state, zip_code] if p and str(p).strip()]
    if not parts:
        return None, None
    query = ", ".join(str(p).strip() for p in parts)
    try:
        resp = http_requests.get(
            "https://nominatim.openstreetmap.org/search",
            params={"q": query, "format": "json", "limit": 1},
            headers={"User-Agent": "EventMapApp/1.0 (self-hosted local app)"},
            timeout=5
        )
        if resp.ok:
            data = resp.json()
            if data:
                return float(data[0]["lat"]), float(data[0]["lon"])
    except Exception as e:
        print(f"[geocode] Failed for '{query}': {e}")
    return None, None

def _normalize_crop_name(name):
    """Trim, collapse spaces, lowercase to match DB naming convention."""
    if not name:
        return name
    return " ".join(name.strip().lower().split())

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
    err = _require_auth()
    if err: return err
    data = request.get_json() or {}
    conn = get_conn()
    try:
        cur = conn.cursor(dictionary=True)
        # Accept category by name (from admin form) or by id
        category_id = data.get('category_id')
        if not category_id and data.get('category'):
            cur.execute("SELECT id FROM categories WHERE name = %s", (data.get('category'),))
            row = cur.fetchone()
            if row:
                category_id = row['id']

        lat = data.get('lat')
        lng = data.get('lng')
        # If coords missing but address present, attempt geocoding
        if (lat is None or lng is None) and any([data.get('address'), data.get('city')]):
            geo_lat, geo_lng = _try_geocode(
                data.get('address'), data.get('city'),
                data.get('state'), data.get('zip')
            )
            if geo_lat is not None:
                lat, lng = geo_lat, geo_lng

        pm = data.get('payment_methods')
        am = data.get('amenities')
        sql = """
            UPDATE locations SET
            name = %s, address = %s, city = %s, state = %s, zip = %s,
            lat = %s, lng = %s, phone = %s, alt_phone = %s, email = %s,
            website = %s, facebook_url = %s, hours = %s, notes = %s,
            category_id = %s, event_date = %s, county = %s,
            season_start_month = %s, season_end_month = %s,
            organic = %s, pesticide_free = %s, low_chemical = %s,
            payment_methods = %s, amenities = %s
            WHERE id = %s
        """
        params = (
            data.get('name'), data.get('address'), data.get('city'),
            data.get('state', 'PA'), data.get('zip'),
            lat, lng,
            data.get('phone'), data.get('alt_phone'), data.get('email'),
            data.get('website'), data.get('facebook_url'),
            data.get('hours'), data.get('notes'),
            category_id, data.get('event_date'), data.get('county'),
            data.get('season_start_month'), data.get('season_end_month'),
            bool(data.get('organic')), bool(data.get('pesticide_free')),
            bool(data.get('low_chemical')),
            json.dumps(pm) if pm is not None else None,
            json.dumps(am) if am is not None else None,
            loc_id
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
    err = _require_auth()
    if err: return err
    data = request.get_json() or {}
    conn = get_conn()
    try:
        cur = conn.cursor(dictionary=True)

        # Duplicate check
        name = data.get('name', '').strip()
        city = data.get('city', '').strip()
        address = data.get('address', '').strip()

        if name and city:
            # Look for exact name/city/address match
            check_sql = "SELECT id, name, city, address FROM locations WHERE name = %s AND city = %s"
            check_params = [name, city]
            if address:
                check_sql += " AND address = %s"
                check_params.append(address)
            else:
                check_sql += " AND (address IS NULL OR address = '')"
            
            check_sql += " LIMIT 1"

            cur.execute(check_sql, tuple(check_params))
            existing = cur.fetchone()
            if existing:
                cur.close()
                return jsonify({
                    "error": "Location already exists",
                    "existing_id": existing['id'],
                    "message": f"A location with name '{name}' already exists in {city} (ID: {existing['id']})."
                }), 409

        # Accept category by name (from admin form) or by id
        category_id = data.get('category_id')
        if not category_id and data.get('category'):
            cur.execute("SELECT id FROM categories WHERE name = %s", (data.get('category'),))
            row = cur.fetchone()
            if row:
                category_id = row['id']

        lat = data.get('lat')
        lng = data.get('lng')
        # If coords missing but address present, attempt geocoding
        if (lat is None or lng is None) and any([data.get('address'), data.get('city')]):
            geo_lat, geo_lng = _try_geocode(
                data.get('address'), data.get('city'),
                data.get('state'), data.get('zip')
            )
            if geo_lat is not None:
                lat, lng = geo_lat, geo_lng

        pm = data.get('payment_methods')
        am = data.get('amenities')
        sql = """
            INSERT INTO locations (
                name, address, city, state, zip, lat, lng,
                phone, alt_phone, email, website, facebook_url,
                hours, notes, category_id, event_date, county,
                season_start_month, season_end_month,
                organic, pesticide_free, low_chemical,
                payment_methods, amenities
            ) VALUES (
                %s, %s, %s, %s, %s, %s, %s,
                %s, %s, %s, %s, %s,
                %s, %s, %s, %s, %s,
                %s, %s,
                %s, %s, %s,
                %s, %s
            )
        """
        params = (
            data.get('name'), data.get('address'), data.get('city'),
            data.get('state', 'PA'), data.get('zip'),
            lat, lng,
            data.get('phone'), data.get('alt_phone'), data.get('email'),
            data.get('website'), data.get('facebook_url'),
            data.get('hours'), data.get('notes'),
            category_id, data.get('event_date'), data.get('county'),
            data.get('season_start_month'), data.get('season_end_month'),
            bool(data.get('organic')), bool(data.get('pesticide_free')),
            bool(data.get('low_chemical')),
            json.dumps(pm) if pm is not None else None,
            json.dumps(am) if am is not None else None
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
    err = _require_auth()
    if err: return err
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
    err = _require_auth()
    if err: return err
    data = request.get_json() or {}
    conn = get_conn()
    try:
        cur = conn.cursor()
        cur.execute("INSERT INTO crops (location_id, name, is_pyo, season_start_month, season_end_month) VALUES (%s, %s, %s, %s, %s)",
            (loc_id, _normalize_crop_name(data.get('name')), data.get('is_pyo'),
             data.get('season_start_month'), data.get('season_end_month')))
        conn.commit()
        cur.close()
        return jsonify({"ok": True})
    finally:
        conn.close()

@app.route("/crops/<int:crop_id>", methods=["PUT"])
@app.route("/api/crops/<int:crop_id>", methods=["PUT"])
def update_loc_crop(crop_id):
    err = _require_auth()
    if err: return err
    data = request.get_json() or {}
    conn = get_conn()
    try:
        cur = conn.cursor()
        cur.execute("UPDATE crops SET name=%s, is_pyo=%s, season_start_month=%s, season_end_month=%s WHERE id=%s",
            (_normalize_crop_name(data.get('name')), data.get('is_pyo'),
             data.get('season_start_month'), data.get('season_end_month'), crop_id))
        conn.commit()
        cur.close()
        return jsonify({"ok": True})
    finally:
        conn.close()

@app.route("/crops/<int:crop_id>", methods=["DELETE"])
@app.route("/api/crops/<int:crop_id>", methods=["DELETE"])
def delete_loc_crop(crop_id):
    err = _require_auth()
    if err: return err
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

@app.route("/map")
@app.route("/map/")
def map_view():
    return app.send_static_file("map.html")

@app.route("/admin/")
def admin_index():
    return app.send_static_file("admin/index.html")


# ── External events API ────────────────────────────────────────────────────────

@app.route("/sources")
@app.route("/api/sources")
def get_sources():
    """Public endpoint: list enabled event sources."""
    conn = get_conn()
    try:
        sources = _events.get_sources(conn, enabled_only=True)
        return jsonify({"sources": sources})
    finally:
        conn.close()


@app.route("/api/admin/sources", methods=["GET"])
def admin_get_sources():
    err = _require_auth()
    if err:
        return err
    conn = get_conn()
    try:
        sources = _events.get_sources(conn, enabled_only=False)
        return jsonify({"sources": sources})
    finally:
        conn.close()


@app.route("/api/admin/sources/<source_key>", methods=["PUT"])
def admin_update_source(source_key):
    err = _require_auth()
    if err:
        return err
    data = request.get_json() or {}
    if "enabled" not in data:
        return jsonify({"error": "enabled field required"}), 400
    enabled = bool(data["enabled"])
    conn = get_conn()
    try:
        cur = conn.cursor()
        cur.execute(
            "UPDATE event_sources SET enabled=%s, updated_at=NOW() WHERE source_key=%s",
            (enabled, source_key)
        )
        if cur.rowcount == 0:
            cur.close()
            return jsonify({"error": "Source not found"}), 404
        conn.commit()
        cur.close()
        return jsonify({"ok": True, "source_key": source_key, "enabled": enabled})
    finally:
        conn.close()


@app.route("/events")
@app.route("/api/events")
def get_events():
    filter_type        = request.args.get("filter")             # legacy: this_weekend
    date_filter        = request.args.get("date_filter")        # today|this_weekend|custom
    start_date         = request.args.get("start_date")         # YYYY-MM-DD
    end_date           = request.args.get("end_date")           # YYYY-MM-DD
    sort               = request.args.get("sort", "soonest")
    saved_only         = request.args.get("saved") == "1"
    max_distance_miles = request.args.get("max_distance_miles", type=float)
    max_drive          = request.args.get("max_drive", type=int)  # legacy
    limit              = request.args.get("limit", type=int, default=100)
    offset             = request.args.get("offset", type=int, default=0)
    # Comma-separated list of source_keys to restrict results
    source_keys_raw    = request.args.get("source_keys", "").strip()
    source_keys        = [s.strip() for s in source_keys_raw.split(",") if s.strip()] or None

    conn = get_conn()
    try:
        stale = _events.any_source_stale(conn)
        if stale:
            _events.trigger_background_refresh(get_conn)

        evs = _events.get_events(
            conn,
            filter_type=filter_type,
            date_filter=date_filter,
            start_date=start_date,
            end_date=end_date,
            sort=sort,
            saved_only=saved_only,
            max_distance_miles=max_distance_miles,
            max_drive_min=max_drive,
            source_keys=source_keys,
            enabled_only=True,
            limit=limit,
            offset=offset,
        )
        return jsonify({
            "events": evs,
            "count": len(evs),
            "limit": limit,
            "offset": offset,
            "cache_stale": stale,
        })
    finally:
        conn.close()


@app.route("/events/refresh", methods=["POST"])
@app.route("/api/events/refresh", methods=["POST"])
def refresh_events():
    err = _require_auth()
    if err:
        return err
    source = request.args.get("source")  # optional: refresh single source
    conn = get_conn()
    try:
        if source:
            count = _events.refresh_source(conn, source)
            results = {source: count}
        else:
            results = _events.refresh_all(conn)
        return jsonify({"ok": True, "refreshed": results})
    except ValueError as e:
        return jsonify({"error": str(e)}), 400
    finally:
        conn.close()


@app.route("/events/<int:ev_id>/save", methods=["POST"])
@app.route("/api/events/<int:ev_id>/save", methods=["POST"])
def save_event(ev_id):
    data = request.get_json() or {}
    saved = data.get("saved", True)
    conn = get_conn()
    try:
        cur = conn.cursor()
        cur.execute("UPDATE external_events SET saved=%s WHERE id=%s", (saved, ev_id))
        conn.commit()
        cur.close()
        return jsonify({"ok": True})
    finally:
        conn.close()


@app.route("/events/<int:ev_id>/hide", methods=["POST"])
@app.route("/api/events/<int:ev_id>/hide", methods=["POST"])
def hide_event(ev_id):
    data = request.get_json() or {}
    hidden = data.get("hidden", True)
    conn = get_conn()
    try:
        cur = conn.cursor()
        cur.execute("UPDATE external_events SET hidden=%s WHERE id=%s", (hidden, ev_id))
        conn.commit()
        cur.close()
        return jsonify({"ok": True})
    finally:
        conn.close()


@app.route("/api/admin/events")
def admin_get_events():
    err = _require_auth()
    if err:
        return err
    include_hidden = request.args.get("include_hidden") == "1"
    source        = request.args.get("source")
    limit         = max(1, min(int(request.args.get("limit", 300)), 500))

    conn = get_conn()
    try:
        # Source summary (all events, no date filter)
        cur = conn.cursor(dictionary=True)
        cur.execute("""
            SELECT es.display_name, e.source_key, es.enabled,
                   COUNT(*) AS total,
                   SUM(e.hidden) AS hidden_count,
                   SUM(e.saved)  AS saved_count
            FROM external_events e
            LEFT JOIN event_sources es ON e.source_key = es.source_key
            GROUP BY e.source_key, es.display_name, es.enabled
        """)
        sources = cur.fetchall()
        cur.close()

        # Coerce Decimal → int / bool for JSON serialisation
        for s in sources:
            s["total"]        = int(s["total"] or 0)
            s["hidden_count"] = int(s["hidden_count"] or 0)
            s["saved_count"]  = int(s["saved_count"] or 0)
            s["enabled"]      = bool(s["enabled"]) if s["enabled"] is not None else True

        # Event list — upcoming + recent, optionally including hidden
        cutoff = datetime.datetime.utcnow() - datetime.timedelta(hours=6)
        conds  = ["(e.start_datetime IS NULL OR e.start_datetime >= %s)"]
        params = [cutoff]
        if not include_hidden:
            conds.append("e.hidden = FALSE")
        if source:
            conds.append("e.source_key = %s")
            params.append(source)
        where = " AND ".join(conds)
        params.append(limit)

        cur2 = conn.cursor(dictionary=True)
        cur2.execute(f"""
            SELECT e.id, e.title, e.source_key, e.source_url, e.venue_name,
                   e.city, e.state, e.start_datetime, e.hidden, e.saved,
                   es.display_name AS display_name
            FROM external_events e
            LEFT JOIN event_sources es ON e.source_key = es.source_key
            WHERE {where}
            ORDER BY e.start_datetime ASC
            LIMIT %s
        """, params)
        events = cur2.fetchall()
        cur2.close()

        for ev in events:
            if ev.get("start_datetime") and isinstance(ev["start_datetime"], datetime.datetime):
                ev["start_datetime"] = ev["start_datetime"].isoformat()
            ev["hidden"] = bool(ev["hidden"])
            ev["saved"]  = bool(ev["saved"])

        return jsonify({"events": events, "sources": sources, "total": len(events)})
    finally:
        conn.close()


if __name__ == "__main__":
    _conn = get_conn()
    _events.ensure_tables(_conn)
    _events.recalculate_all_distances(_conn)
    _conn.close()
    app.run(host="0.0.0.0", port=8080)
