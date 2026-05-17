import json
import os
import sys

# Allow direct import of api/ modules
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "api"))
from app import get_conn

def export_manifest():
    conn = get_conn()
    cur = conn.cursor(dictionary=True)

    cur.execute("SELECT id, name, icon, color, display_order FROM categories")
    categories = cur.fetchall()

    cur.execute(
        "SELECT name, category_id, county, address, city, state, zip, lat, lng, "
        "phone, alt_phone, fax, email, website, facebook_url, hours, event_date, "
        "season_start_month, season_end_month, payment_methods, amenities, "
        "organic, pesticide_free, low_chemical, notes, source_url "
        "FROM locations"
    )
    locations = cur.fetchall()

    # Convert datatypes (like Decimals to float)
    def clean_dict(d):
        for k, v in list(d.items()):
            if v is not None:
                if hasattr(v, "normalize"): # Decimal
                    d[k] = float(v)
        return d

    for loc in locations:
        clean_dict(loc)

    manifest = {
        "categories": categories,
        "locations": locations
    }

    with open("/app/api/data/seed_manifest.json", "w") as f:
        json.dump(manifest, f, indent=2)

    cur.close()
    conn.close()

if __name__ == "__main__":
    export_manifest()
