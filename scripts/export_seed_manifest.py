import json
import os
import sys
import hashlib
import re

# Allow direct import of api/ modules
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "api"))
from app import get_conn

def generate_seed_key(category_name, location_name):
    # e.g., hiking-trails_beechwood_farms_nature_reserve
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

def export_manifest():
    conn = get_conn()
    cur = conn.cursor(dictionary=True)

    cur.execute("SELECT id, name, icon, color, display_order FROM categories")
    categories = cur.fetchall()

    cat_id_to_name = {c["id"]: c["name"] for c in categories}

    cur.execute(
        "SELECT id, name, category_id, county, address, city, state, zip, lat, lng, "
        "phone, alt_phone, fax, email, website, facebook_url, hours, event_date, "
        "season_start_month, season_end_month, payment_methods, amenities, "
        "organic, pesticide_free, low_chemical, notes, source_url, seed_managed "
        "FROM locations "
        "WHERE seed_managed = TRUE OR category_id IN (SELECT id FROM categories WHERE name IN ('hiking-trails', 'butcher'))"
    )
    locations = cur.fetchall()

    def clean_dict(d):
        for k, v in list(d.items()):
            if v is not None:
                if hasattr(v, "normalize"): # Decimal
                    d[k] = float(v)
        return d

    manifest_locs = []
    for loc in locations:
        clean_dict(loc)
        cat_name = cat_id_to_name.get(loc.get("category_id"), "")
        loc["category_name"] = cat_name
        
        # Calculate seed_key and seed_hash
        s_key = generate_seed_key(cat_name, loc["name"])
        s_hash = hash_seed_data(loc)
        loc["seed_key"] = s_key
        loc["seed_hash"] = s_hash
        
        # We only want to export the fields that are actually managed by the seed
        manifest_locs.append({
            "seed_key": s_key,
            "seed_hash": s_hash,
            "name": loc.get("name"),
            "category_name": loc.get("category_name"),
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
            "notes": loc.get("notes")
        })

    manifest = {
        "categories": categories,
        "locations": manifest_locs
    }

    # Print to stdout so bash can redirect it
    print(json.dumps(manifest, indent=2))

    cur.close()
    conn.close()

if __name__ == "__main__":
    export_manifest()