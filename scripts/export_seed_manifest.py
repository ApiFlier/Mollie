import json
import os
import sys
import hashlib
import re
import mysql.connector
import decimal


def _get_direct_conn():
    """Single direct (non-pooled) connection using the container env vars.

    Avoids importing app.py, which would create a 15-connection pool and exceed
    MySQL's max_connections=20 while the app container is already running.
    """
    return mysql.connector.connect(
        host=os.environ.get("DB_HOST", "db"),
        database=os.environ.get("DB_NAME", "event_map"),
        user=os.environ.get("DB_USER", "event_map"),
        password=os.environ.get("DB_PASSWORD", ""),
        connection_timeout=10,
    )


def generate_seed_key(category_name, location_name):
    cat = str(category_name).lower().strip()
    loc = str(location_name).lower().strip()
    slug = re.sub(r'[^a-z0-9]+', '_', f"{cat}_{loc}")
    return slug[:128]


def hash_seed_data(loc_dict):
    keys = ["name", "category_name", "county", "address", "city", "state", "zip",
            "lat", "lng", "website", "season_start_month", "season_end_month", "notes"]
    parts = []
    for k in keys:
        val = loc_dict.get(k)
        if val is None:
            parts.append("")
        elif isinstance(val, float):
            parts.append(f"{val:.5f}")
        else:
            parts.append(str(val).strip())
    raw = "|".join(parts)
    return hashlib.md5(raw.encode('utf-8')).hexdigest()


def _clean(d):
    """Coerce Decimal to float so json.dumps doesn't choke."""
    for k, v in list(d.items()):
        if isinstance(v, decimal.Decimal):
            d[k] = float(v)
    return d


def export_manifest():
    conn = _get_direct_conn()
    cur = conn.cursor(dictionary=True)

    cur.execute("SELECT id, name, icon, color, display_order FROM categories ORDER BY display_order")
    categories = cur.fetchall()
    cat_id_to_name = {c["id"]: c["name"] for c in categories}

    # Export all curated locations (everything except runtime external_events).
    # The old filter used seed_managed=TRUE which no longer exists in the live DB.
    cur.execute(
        "SELECT id, name, category_id, county, address, city, state, zip, lat, lng, "
        "phone, alt_phone, fax, email, website, facebook_url, hours, event_date, "
        "season_start_month, season_end_month, payment_methods, amenities, "
        "organic, pesticide_free, low_chemical, notes, source_url "
        "FROM locations "
        "ORDER BY category_id, name"
    )
    locations = cur.fetchall()

    manifest_locs = []
    for loc in locations:
        _clean(loc)
        cat_name = cat_id_to_name.get(loc.get("category_id"), "")
        loc["category_name"] = cat_name
        s_key = generate_seed_key(cat_name, loc["name"])
        s_hash = hash_seed_data(loc)
        manifest_locs.append({
            "seed_key": s_key,
            "seed_hash": s_hash,
            "name": loc.get("name"),
            "category_name": cat_name,
            "county": loc.get("county"),
            "address": loc.get("address"),
            "city": loc.get("city"),
            "state": loc.get("state"),
            "zip": loc.get("zip"),
            "lat": loc.get("lat"),
            "lng": loc.get("lng"),
            "website": loc.get("website"),
            "season_start_month": loc.get("season_start_month"),
            "season_end_month": loc.get("season_end_month"),
            "notes": loc.get("notes"),
        })

    manifest = {
        "categories": categories,
        "locations": manifest_locs,
    }

    print(json.dumps(manifest, indent=2))

    cur.close()
    conn.close()


if __name__ == "__main__":
    export_manifest()
