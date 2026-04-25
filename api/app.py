"""
Mollie's Guide API

Endpoints:
  GET /health                        - liveness check
  GET /locations                     - all locations (with optional filters)
  GET /locations/<id>                - single location with crops
  GET /categories                    - list of categories
  GET /crops/distinct                - distinct crop names (for filter dropdowns)

Filters on /locations:
  ?category=pick-your-own,orchard    - comma-separated category names
  ?month=7                           - only locations with crops in season this month
  ?crop=blueberries                  - only locations growing this crop
  ?pyo_only=true                     - only locations with at least one PYO crop
  ?organic=true                      - organic only
"""

import os
import json
import logging
from flask import Flask, jsonify, request
from flask_cors import CORS
import mysql.connector
from mysql.connector import pooling
import bcrypt
import os.path

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
log = logging.getLogger(__name__)

app = Flask(__name__)
CORS(app)

DB_CONFIG = {
    "host": os.environ.get("DB_HOST", "db"),
    "port": int(os.environ.get("DB_PORT", "3306")),
    "database": os.environ.get("DB_NAME", "mollies_guide"),
    "user": os.environ.get("DB_USER", "mollies"),
    "password": os.environ.get("DB_PASSWORD", ""),
    "pool_name": "mollies_pool",
    "pool_size": 5,
}

# Pool initializes lazily on first request
_pool = None


def get_pool():
    global _pool
    if _pool is None:
        _pool = pooling.MySQLConnectionPool(**DB_CONFIG)
    return _pool


def get_conn():
    return get_pool().get_connection()


def parse_bool(value):
    if value is None:
        return None
    return str(value).lower() in ("1", "true", "yes", "y")


# -------- Endpoints --------

@app.route("/health")
def health():
    try:
        conn = get_conn()
        cur = conn.cursor()
        cur.execute("SELECT 1")
        cur.fetchone()
        cur.close()
        conn.close()
        return jsonify({"status": "ok", "database": "connected"})
    except Exception as e:
        log.error(f"Health check failed: {e}")
        return jsonify({"status": "error", "error": str(e)}), 500


@app.route("/categories")
def get_categories():
    conn = get_conn()
    cur = conn.cursor(dictionary=True)
    cur.execute("SELECT id, name, icon, color, display_order FROM categories ORDER BY display_order")
    cats = cur.fetchall()
    cur.close()
    conn.close()
    return jsonify(cats)


@app.route("/locations")
def get_locations():
    # Parse filters
    category_filter = request.args.get("category")
    month_filter = request.args.get("month", type=int)
    crop_filter = request.args.get("crop", "").strip().lower()
    pyo_only = parse_bool(request.args.get("pyo_only"))
    organic = parse_bool(request.args.get("organic"))

    conn = get_conn()
    cur = conn.cursor(dictionary=True)

    # Build location query
    where = []
    params = []

    if category_filter:
        cats = [c.strip() for c in category_filter.split(",") if c.strip()]
        if cats:
            placeholders = ",".join(["%s"] * len(cats))
            where.append(f"c.name IN ({placeholders})")
            params.extend(cats)

    if organic:
        where.append("l.organic = 1")

    # Month/crop filters need an EXISTS subquery against crops
    crop_subquery_parts = []
    crop_subquery_params = []
    if month_filter is not None:
        crop_subquery_parts.append(
            "(%s BETWEEN cr.season_start_month AND cr.season_end_month "
            "OR (cr.season_start_month > cr.season_end_month "
            "    AND (%s >= cr.season_start_month OR %s <= cr.season_end_month)))"
        )
        crop_subquery_params.extend([month_filter, month_filter, month_filter])
    if crop_filter:
        crop_subquery_parts.append("LOWER(cr.name) LIKE %s")
        crop_subquery_params.append(f"%{crop_filter}%")
    if pyo_only:
        crop_subquery_parts.append("cr.is_pyo = 1")

    if crop_subquery_parts:
        sub = (
            "EXISTS (SELECT 1 FROM crops cr WHERE cr.location_id = l.id AND "
            + " AND ".join(crop_subquery_parts)
            + ")"
        )
        where.append(sub)
        params.extend(crop_subquery_params)

    where_clause = " WHERE " + " AND ".join(where) if where else ""

    sql = f"""
        SELECT 
            l.id, l.name, l.county, l.address, l.city, l.state, l.zip,
            l.lat, l.lng, l.phone, l.alt_phone, l.email, l.website,
            l.facebook_url, l.hours, l.payment_methods, l.amenities,
            l.organic, l.pesticide_free, l.low_chemical, l.notes,
            c.name AS category, c.color AS category_color, c.icon AS category_icon
        FROM locations l
        LEFT JOIN categories c ON l.category_id = c.id
        {where_clause}
        ORDER BY l.name
    """

    cur.execute(sql, params)
    locations = cur.fetchall()

    # Convert numeric/JSON fields and attach crops
    location_ids = [loc["id"] for loc in locations]
    crops_by_loc = {}
    if location_ids:
        ph = ",".join(["%s"] * len(location_ids))
        cur.execute(
            f"""
            SELECT location_id, name, is_pyo, season_start_month, season_end_month
            FROM crops
            WHERE location_id IN ({ph})
            ORDER BY season_start_month, name
            """,
            location_ids,
        )
        for row in cur.fetchall():
            crops_by_loc.setdefault(row["location_id"], []).append({
                "name": row["name"],
                "is_pyo": bool(row["is_pyo"]),
                "season_start_month": row["season_start_month"],
                "season_end_month": row["season_end_month"],
            })

    for loc in locations:
        # Cast Decimal to float for JSON
        if loc["lat"] is not None:
            loc["lat"] = float(loc["lat"])
        if loc["lng"] is not None:
            loc["lng"] = float(loc["lng"])
        # JSON columns come back as strings in some MySQL connector versions
        for field in ("payment_methods", "amenities"):
            v = loc.get(field)
            if isinstance(v, str):
                try:
                    loc[field] = json.loads(v)
                except Exception:
                    loc[field] = []
        # Boolean casts
        for field in ("organic", "pesticide_free", "low_chemical"):
            loc[field] = bool(loc[field])
        loc["crops"] = crops_by_loc.get(loc["id"], [])

    cur.close()
    conn.close()
    return jsonify(locations)


@app.route("/locations/<int:loc_id>")
def get_location(loc_id):
    conn = get_conn()
    cur = conn.cursor(dictionary=True)
    cur.execute(
        """
        SELECT 
            l.*, 
            c.name AS category, c.color AS category_color, c.icon AS category_icon
        FROM locations l
        LEFT JOIN categories c ON l.category_id = c.id
        WHERE l.id = %s
        """,
        (loc_id,),
    )
    loc = cur.fetchone()
    if not loc:
        cur.close()
        conn.close()
        return jsonify({"error": "not found"}), 404

    cur.execute(
        """
        SELECT name, is_pyo, season_start_month, season_end_month, notes
        FROM crops 
        WHERE location_id = %s 
        ORDER BY season_start_month, name
        """,
        (loc_id,),
    )
    crops = cur.fetchall()

    cur.close()
    conn.close()

    if loc["lat"] is not None:
        loc["lat"] = float(loc["lat"])
    if loc["lng"] is not None:
        loc["lng"] = float(loc["lng"])
    for field in ("payment_methods", "amenities"):
        v = loc.get(field)
        if isinstance(v, str):
            try:
                loc[field] = json.loads(v)
            except Exception:
                loc[field] = []
    for field in ("organic", "pesticide_free", "low_chemical"):
        loc[field] = bool(loc[field])
    for crop in crops:
        crop["is_pyo"] = bool(crop["is_pyo"])
    loc["crops"] = crops

    return jsonify(loc)


@app.route("/crops/distinct")
def get_distinct_crops():
    """Distinct crop names for populating the filter dropdown."""
    conn = get_conn()
    cur = conn.cursor(dictionary=True)
    cur.execute(
        """
        SELECT name, COUNT(DISTINCT location_id) AS farm_count
        FROM crops
        GROUP BY name
        ORDER BY farm_count DESC, name
        """
    )
    crops = cur.fetchall()
    cur.close()
    conn.close()
    return jsonify(crops)



@app.route("/locations/<int:loc_id>/notes", methods=["GET"])
def list_notes(loc_id):
    conn = get_conn()
    cur = conn.cursor(dictionary=True)
    cur.execute(
        "SELECT id, note, created_at FROM user_notes WHERE location_id = %s ORDER BY created_at DESC, id DESC",
        (loc_id,),
    )
    notes = cur.fetchall()
    cur.close()
    conn.close()
    for n in notes:
        if n.get("created_at"):
            n["created_at"] = n["created_at"].isoformat()
    return jsonify(notes)


@app.route("/locations/<int:loc_id>/notes", methods=["POST"])
def add_note(loc_id):
    body = request.get_json(silent=True) or {}
    note_text = (body.get("note") or "").strip()
    if not note_text:
        return jsonify({"error": "note text is required"}), 400
    if len(note_text) > 4000:
        return jsonify({"error": "note too long (max 4000 chars)"}), 400

    conn = get_conn()
    cur = conn.cursor(dictionary=True)
    # Verify location exists
    cur.execute("SELECT id FROM locations WHERE id = %s", (loc_id,))
    if not cur.fetchone():
        cur.close()
        conn.close()
        return jsonify({"error": "location not found"}), 404

    cur.execute(
        "INSERT INTO user_notes (location_id, note) VALUES (%s, %s)",
        (loc_id, note_text),
    )
    new_id = cur.lastrowid
    conn.commit()

    cur.execute(
        "SELECT id, note, created_at FROM user_notes WHERE id = %s",
        (new_id,),
    )
    row = cur.fetchone()
    cur.close()
    conn.close()
    if row.get("created_at"):
        row["created_at"] = row["created_at"].isoformat()
    return jsonify(row), 201


@app.route("/notes/<int:note_id>", methods=["DELETE"])
def delete_note(note_id):
    conn = get_conn()
    cur = conn.cursor()
    cur.execute("DELETE FROM user_notes WHERE id = %s", (note_id,))
    deleted = cur.rowcount
    conn.commit()
    cur.close()
    conn.close()
    if deleted == 0:
        return jsonify({"error": "note not found"}), 404
    return jsonify({"deleted": note_id})



# -------- Admin endpoints --------

def _location_payload_from_request():
    """Pulls and validates fields from request.json for create/update."""
    body = request.get_json(silent=True) or {}
    payload = {
        "name": (body.get("name") or "").strip(),
        "category_id": body.get("category_id"),
        "county": (body.get("county") or "").strip() or None,
        "address": (body.get("address") or "").strip() or None,
        "city": (body.get("city") or "").strip() or None,
        "state": (body.get("state") or "PA").strip()[:2].upper(),
        "zip": (body.get("zip") or "").strip() or None,
        "lat": body.get("lat"),
        "lng": body.get("lng"),
        "phone": (body.get("phone") or "").strip() or None,
        "alt_phone": (body.get("alt_phone") or "").strip() or None,
        "email": (body.get("email") or "").strip() or None,
        "website": (body.get("website") or "").strip() or None,
        "facebook_url": (body.get("facebook_url") or "").strip() or None,
        "hours": (body.get("hours") or "").strip() or None,
        "payment_methods": body.get("payment_methods") or [],
        "amenities": body.get("amenities") or [],
        "organic": bool(body.get("organic")),
        "pesticide_free": bool(body.get("pesticide_free")),
        "low_chemical": bool(body.get("low_chemical")),
        "notes": body.get("notes") or "",
    }
    # Cast lat/lng to float or None
    for f in ("lat", "lng"):
        if payload[f] in ("", None):
            payload[f] = None
        else:
            try:
                payload[f] = float(payload[f])
            except (TypeError, ValueError):
                payload[f] = None
    if not payload["name"]:
        return None, "name is required"
    if payload["category_id"] in ("", None):
        return None, "category_id is required"
    try:
        payload["category_id"] = int(payload["category_id"])
    except (TypeError, ValueError):
        return None, "category_id must be integer"
    return payload, None


@app.route("/admin/locations", methods=["POST"])
def admin_create_location():
    payload, err = _location_payload_from_request()
    if err:
        return jsonify({"error": err}), 400
    conn = get_conn()
    cur = conn.cursor()
    cur.execute(
        """
        INSERT INTO locations (
            name, category_id, county, address, city, state, zip,
            lat, lng, phone, alt_phone, email, website, facebook_url,
            hours, payment_methods, amenities,
            organic, pesticide_free, low_chemical, notes
        ) VALUES (
            %(name)s, %(category_id)s, %(county)s, %(address)s, %(city)s, %(state)s, %(zip)s,
            %(lat)s, %(lng)s, %(phone)s, %(alt_phone)s, %(email)s, %(website)s, %(facebook_url)s,
            %(hours)s, %(payment_methods_json)s, %(amenities_json)s,
            %(organic)s, %(pesticide_free)s, %(low_chemical)s, %(notes)s
        )
        """,
        {
            **payload,
            "payment_methods_json": json.dumps(payload["payment_methods"]),
            "amenities_json": json.dumps(payload["amenities"]),
        },
    )
    new_id = cur.lastrowid
    conn.commit()
    cur.close()
    conn.close()
    return jsonify({"id": new_id}), 201


@app.route("/admin/locations/<int:loc_id>", methods=["PUT"])
def admin_update_location(loc_id):
    payload, err = _location_payload_from_request()
    if err:
        return jsonify({"error": err}), 400
    conn = get_conn()
    cur = conn.cursor()
    cur.execute(
        """
        UPDATE locations SET
            name = %(name)s, category_id = %(category_id)s, county = %(county)s,
            address = %(address)s, city = %(city)s, state = %(state)s, zip = %(zip)s,
            lat = %(lat)s, lng = %(lng)s,
            phone = %(phone)s, alt_phone = %(alt_phone)s, email = %(email)s,
            website = %(website)s, facebook_url = %(facebook_url)s, hours = %(hours)s,
            payment_methods = %(payment_methods_json)s, amenities = %(amenities_json)s,
            organic = %(organic)s, pesticide_free = %(pesticide_free)s,
            low_chemical = %(low_chemical)s, notes = %(notes)s
        WHERE id = %(id)s
        """,
        {
            **payload,
            "id": loc_id,
            "payment_methods_json": json.dumps(payload["payment_methods"]),
            "amenities_json": json.dumps(payload["amenities"]),
        },
    )
    affected = cur.rowcount
    conn.commit()
    cur.close()
    conn.close()
    if affected == 0:
        return jsonify({"error": "location not found"}), 404
    return jsonify({"updated": loc_id})


@app.route("/admin/locations/<int:loc_id>", methods=["DELETE"])
def admin_delete_location(loc_id):
    conn = get_conn()
    cur = conn.cursor()
    cur.execute("DELETE FROM locations WHERE id = %s", (loc_id,))
    affected = cur.rowcount
    conn.commit()
    cur.close()
    conn.close()
    if affected == 0:
        return jsonify({"error": "location not found"}), 404
    return jsonify({"deleted": loc_id})


@app.route("/admin/locations/<int:loc_id>/crops", methods=["PUT"])
def admin_replace_crops(loc_id):
    """Replace the entire crop list for a location. Body: {crops: [...]}"""
    body = request.get_json(silent=True) or {}
    crops = body.get("crops", [])
    if not isinstance(crops, list):
        return jsonify({"error": "crops must be a list"}), 400

    conn = get_conn()
    cur = conn.cursor()
    cur.execute("SELECT id FROM locations WHERE id = %s", (loc_id,))
    if not cur.fetchone():
        cur.close()
        conn.close()
        return jsonify({"error": "location not found"}), 404

    cur.execute("DELETE FROM crops WHERE location_id = %s", (loc_id,))
    for c in crops:
        name = (c.get("name") or "").strip().lower()
        if not name:
            continue
        cur.execute(
            """
            INSERT INTO crops (location_id, name, is_pyo, season_start_month, season_end_month)
            VALUES (%s, %s, %s, %s, %s)
            """,
            (
                loc_id,
                name,
                bool(c.get("is_pyo", True)),
                c.get("season_start_month") or None,
                c.get("season_end_month") or None,
            ),
        )
    conn.commit()
    cur.close()
    conn.close()
    return jsonify({"updated": loc_id, "crop_count": len(crops)})


@app.route("/admin/amenities-vocab", methods=["GET"])
def admin_amenities_vocab():
    """Returns the union of all amenity strings used across locations,
    so the admin form can show known options as checkboxes."""
    conn = get_conn()
    cur = conn.cursor(dictionary=True)
    cur.execute("SELECT amenities FROM locations WHERE amenities IS NOT NULL")
    seen = set()
    for row in cur.fetchall():
        v = row["amenities"]
        if isinstance(v, str):
            try:
                v = json.loads(v)
            except Exception:
                v = []
        if isinstance(v, list):
            for a in v:
                if a:
                    seen.add(a.strip().lower())
    cur.close()
    conn.close()
    return jsonify(sorted(seen))


@app.route("/admin/payment-vocab", methods=["GET"])
def admin_payment_vocab():
    """Same idea for payment methods."""
    conn = get_conn()
    cur = conn.cursor(dictionary=True)
    cur.execute("SELECT payment_methods FROM locations WHERE payment_methods IS NOT NULL")
    seen = set()
    for row in cur.fetchall():
        v = row["payment_methods"]
        if isinstance(v, str):
            try:
                v = json.loads(v)
            except Exception:
                v = []
        if isinstance(v, list):
            for a in v:
                if a:
                    seen.add(a.strip().lower())
    cur.close()
    conn.close()
    return jsonify(sorted(seen))



# ---------- Admin endpoints ----------

VALID_BOOLS = ("organic", "pesticide_free", "low_chemical")


def _location_payload_to_db(body, cat_map):
    """Normalize a JSON body into the args we INSERT/UPDATE with."""
    cat_id = cat_map.get(body.get("category")) if body.get("category") else None

    payment_methods = body.get("payment_methods") or []
    amenities = body.get("amenities") or []
    if isinstance(payment_methods, str):
        payment_methods = [s.strip() for s in payment_methods.split(",") if s.strip()]
    if isinstance(amenities, str):
        amenities = [s.strip() for s in amenities.split(",") if s.strip()]

    return {
        "name": (body.get("name") or "").strip(),
        "category_id": cat_id,
        "county": body.get("county"),
        "address": body.get("address"),
        "city": body.get("city"),
        "state": (body.get("state") or "PA")[:2],
        "zip": body.get("zip"),
        "lat": body.get("lat"),
        "lng": body.get("lng"),
        "phone": body.get("phone"),
        "alt_phone": body.get("alt_phone"),
        "fax": body.get("fax"),
        "email": body.get("email"),
        "website": body.get("website"),
        "facebook_url": body.get("facebook_url"),
        "hours": body.get("hours"),
        "payment_methods": json.dumps(payment_methods),
        "amenities": json.dumps(amenities),
        "organic": bool(body.get("organic")),
        "pesticide_free": bool(body.get("pesticide_free")),
        "low_chemical": bool(body.get("low_chemical")),
        "notes": body.get("notes") or "",
    }


def _get_category_map(cur):
    cur.execute("SELECT id, name FROM categories")
    return {row["name"]: row["id"] for row in cur.fetchall()}


@app.route("/locations", methods=["POST"])
def create_location():
    body = request.get_json(silent=True) or {}
    if not (body.get("name") or "").strip():
        return jsonify({"error": "name is required"}), 400

    conn = get_conn()
    cur = conn.cursor(dictionary=True)
    cat_map = _get_category_map(cur)
    data = _location_payload_to_db(body, cat_map)

    cur.execute("""
        INSERT INTO locations (
            name, category_id, county, address, city, state, zip,
            lat, lng, phone, alt_phone, fax, email, website,
            facebook_url, hours, payment_methods, amenities,
            organic, pesticide_free, low_chemical, notes
        ) VALUES (
            %(name)s, %(category_id)s, %(county)s, %(address)s, %(city)s, %(state)s, %(zip)s,
            %(lat)s, %(lng)s, %(phone)s, %(alt_phone)s, %(fax)s, %(email)s, %(website)s,
            %(facebook_url)s, %(hours)s, %(payment_methods)s, %(amenities)s,
            %(organic)s, %(pesticide_free)s, %(low_chemical)s, %(notes)s
        )
    """, data)
    new_id = cur.lastrowid
    conn.commit()
    cur.close()
    conn.close()
    return jsonify({"id": new_id}), 201


@app.route("/locations/<int:loc_id>", methods=["PUT"])
def update_location(loc_id):
    body = request.get_json(silent=True) or {}
    if not (body.get("name") or "").strip():
        return jsonify({"error": "name is required"}), 400

    conn = get_conn()
    cur = conn.cursor(dictionary=True)
    cat_map = _get_category_map(cur)
    data = _location_payload_to_db(body, cat_map)
    data["id"] = loc_id

    cur.execute("""
        UPDATE locations SET
            name = %(name)s,
            category_id = %(category_id)s,
            county = %(county)s,
            address = %(address)s,
            city = %(city)s,
            state = %(state)s,
            zip = %(zip)s,
            lat = %(lat)s,
            lng = %(lng)s,
            phone = %(phone)s,
            alt_phone = %(alt_phone)s,
            fax = %(fax)s,
            email = %(email)s,
            website = %(website)s,
            facebook_url = %(facebook_url)s,
            hours = %(hours)s,
            payment_methods = %(payment_methods)s,
            amenities = %(amenities)s,
            organic = %(organic)s,
            pesticide_free = %(pesticide_free)s,
            low_chemical = %(low_chemical)s,
            notes = %(notes)s
        WHERE id = %(id)s
    """, data)
    affected = cur.rowcount
    conn.commit()
    cur.close()
    conn.close()
    if affected == 0:
        # rowcount=0 can mean "no change" or "not found" - check separately
        conn = get_conn()
        cur = conn.cursor()
        cur.execute("SELECT 1 FROM locations WHERE id = %s", (loc_id,))
        exists = cur.fetchone() is not None
        cur.close()
        conn.close()
        if not exists:
            return jsonify({"error": "location not found"}), 404
    return jsonify({"id": loc_id, "updated": True})


@app.route("/locations/<int:loc_id>", methods=["DELETE"])
def delete_location(loc_id):
    conn = get_conn()
    cur = conn.cursor()
    cur.execute("DELETE FROM locations WHERE id = %s", (loc_id,))
    deleted = cur.rowcount
    conn.commit()
    cur.close()
    conn.close()
    if deleted == 0:
        return jsonify({"error": "location not found"}), 404
    return jsonify({"deleted": loc_id})


@app.route("/locations/<int:loc_id>/crops", methods=["POST"])
def create_crop(loc_id):
    body = request.get_json(silent=True) or {}
    name = (body.get("name") or "").strip()
    if not name:
        return jsonify({"error": "crop name is required"}), 400

    conn = get_conn()
    cur = conn.cursor(dictionary=True)
    cur.execute("SELECT id FROM locations WHERE id = %s", (loc_id,))
    if not cur.fetchone():
        cur.close()
        conn.close()
        return jsonify({"error": "location not found"}), 404

    cur.execute("""
        INSERT INTO crops (location_id, name, is_pyo, season_start_month, season_end_month, notes)
        VALUES (%s, %s, %s, %s, %s, %s)
    """, (
        loc_id,
        name,
        bool(body.get("is_pyo", True)),
        body.get("season_start_month"),
        body.get("season_end_month"),
        body.get("notes") or "",
    ))
    new_id = cur.lastrowid
    conn.commit()
    cur.close()
    conn.close()
    return jsonify({"id": new_id}), 201


@app.route("/crops/<int:crop_id>", methods=["PUT"])
def update_crop(crop_id):
    body = request.get_json(silent=True) or {}
    name = (body.get("name") or "").strip()
    if not name:
        return jsonify({"error": "crop name is required"}), 400

    conn = get_conn()
    cur = conn.cursor()
    cur.execute("""
        UPDATE crops SET
            name = %s,
            is_pyo = %s,
            season_start_month = %s,
            season_end_month = %s,
            notes = %s
        WHERE id = %s
    """, (
        name,
        bool(body.get("is_pyo", True)),
        body.get("season_start_month"),
        body.get("season_end_month"),
        body.get("notes") or "",
        crop_id,
    ))
    affected = cur.rowcount
    conn.commit()
    cur.close()
    conn.close()
    return jsonify({"id": crop_id, "updated": True}) if affected else (jsonify({"error": "crop not found"}), 404)


@app.route("/crops/<int:crop_id>", methods=["DELETE"])
def delete_crop(crop_id):
    conn = get_conn()
    cur = conn.cursor()
    cur.execute("DELETE FROM crops WHERE id = %s", (crop_id,))
    deleted = cur.rowcount
    conn.commit()
    cur.close()
    conn.close()
    if deleted == 0:
        return jsonify({"error": "crop not found"}), 404
    return jsonify({"deleted": crop_id})


@app.route("/counties", methods=["GET"])
def list_counties():
    conn = get_conn()
    cur = conn.cursor(dictionary=True)
    cur.execute("""
        SELECT DISTINCT county FROM locations 
        WHERE county IS NOT NULL AND county != ''
        ORDER BY county
    """)
    rows = cur.fetchall()
    cur.close()
    conn.close()
    return jsonify([r["county"] for r in rows])



HTPASSWD_PATH = "/etc/nginx/.htpasswd"


@app.route("/credentials", methods=["GET"])
def credentials_info():
    """Return the current admin username (for the form), no password."""
    try:
        with open(HTPASSWD_PATH) as f:
            line = f.readline().strip()
        username = line.split(":", 1)[0] if ":" in line else ""
        return jsonify({"username": username})
    except Exception as e:
        return jsonify({"error": str(e)}), 500


@app.route("/credentials", methods=["PUT"])
def update_credentials():
    """
    Update admin username and/or password.
    Requires the current password to be supplied.
    """
    body = request.get_json(silent=True) or {}
    current_password = body.get("current_password") or ""
    new_username = (body.get("new_username") or "").strip()
    new_password = body.get("new_password") or ""

    if not new_username:
        return jsonify({"error": "new_username is required"}), 400
    if not new_password:
        return jsonify({"error": "new_password is required"}), 400

    # Verify current password
    try:
        with open(HTPASSWD_PATH) as f:
            line = f.readline().strip()
    except Exception as e:
        return jsonify({"error": "could not read credentials file: " + str(e)}), 500

    if ":" not in line:
        return jsonify({"error": "credentials file is malformed"}), 500

    _, current_hash = line.split(":", 1)
    if not bcrypt.checkpw(current_password.encode("utf-8"), current_hash.encode("utf-8")):
        return jsonify({"error": "current password is incorrect"}), 401

    # Generate new hash and write file
    new_hash = bcrypt.hashpw(new_password.encode("utf-8"), bcrypt.gensalt(rounds=5)).decode("utf-8")
    new_line = f"{new_username}:{new_hash}\n"

    try:
        with open(HTPASSWD_PATH, "w") as f:
            f.write(new_line)
    except Exception as e:
        return jsonify({"error": "could not write credentials file: " + str(e)}), 500

    return jsonify({"updated": True, "username": new_username})


if __name__ == "__main__":
    app.run(host="0.0.0.0", port=8080, debug=True)
