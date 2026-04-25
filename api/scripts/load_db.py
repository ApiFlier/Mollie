#!/usr/bin/env python3
"""
Load mollies_guide_geocoded.json into MySQL.

Connects to the database container (or a configurable host) and:
1. Truncates locations and crops tables (categories stay - they're seeded)
2. Inserts each location and its crops
3. Reports counts
"""

import json
import os
import sys
from pathlib import Path
import mysql.connector

DATA_DIR = Path(__file__).resolve().parent.parent / "data"
INPUT_FILE = DATA_DIR / "mollies_guide_geocoded.json"

DB_CONFIG = {
    "host": os.environ.get("DB_HOST", "localhost"),
    "port": int(os.environ.get("DB_PORT", "3308")),  # 3308 from host, 3306 from container
    "database": os.environ.get("DB_NAME", "mollies_guide"),
    "user": os.environ.get("DB_USER", "mollies"),
    "password": os.environ.get("DB_PASSWORD", ""),
}


def main():
    if not INPUT_FILE.exists():
        print(f"ERROR: {INPUT_FILE} not found", file=sys.stderr)
        sys.exit(1)

    if not DB_CONFIG["password"]:
        print("ERROR: DB_PASSWORD env var is not set", file=sys.stderr)
        print("Run with: DB_PASSWORD=xxx python3 load_db.py", file=sys.stderr)
        sys.exit(1)

    with open(INPUT_FILE) as f:
        data = json.load(f)

    conn = mysql.connector.connect(**DB_CONFIG)
    cur = conn.cursor(dictionary=True)

    # Look up category id by name
    cur.execute("SELECT id, name FROM categories")
    cat_map = {row["name"]: row["id"] for row in cur.fetchall()}
    print(f"Loaded {len(cat_map)} categories from db: {list(cat_map.keys())}")

    # Wipe locations and crops (CASCADE will handle the crops)
    print("Truncating locations and crops...")
    cur.execute("SET FOREIGN_KEY_CHECKS = 0")
    cur.execute("TRUNCATE TABLE crops")
    cur.execute("TRUNCATE TABLE locations")
    cur.execute("SET FOREIGN_KEY_CHECKS = 1")

    locations = data["locations"]
    sources = data.get("sources", [])
    primary_source = sources[0] if sources else None

    loc_count = 0
    crop_count = 0
    skipped = []

    for loc in locations:
        if loc.get("lat") is None or loc.get("lng") is None:
            skipped.append(loc.get("name"))
            continue

        cat_id = cat_map.get(loc.get("category"))

        cur.execute(
            """
            INSERT INTO locations (
                name, category_id, county, address, city, state, zip,
                lat, lng, phone, alt_phone, fax, email, website,
                facebook_url, hours, payment_methods, amenities,
                organic, pesticide_free, low_chemical, notes, source_url
            ) VALUES (
                %s, %s, %s, %s, %s, %s, %s,
                %s, %s, %s, %s, %s, %s, %s,
                %s, %s, %s, %s,
                %s, %s, %s, %s, %s
            )
            """,
            (
                loc.get("name"),
                cat_id,
                loc.get("county"),
                loc.get("address"),
                loc.get("city"),
                loc.get("state"),
                loc.get("zip"),
                loc["lat"],
                loc["lng"],
                loc.get("phone"),
                loc.get("alt_phone"),
                loc.get("fax"),
                loc.get("email"),
                loc.get("website"),
                loc.get("facebook_url"),
                loc.get("hours"),
                json.dumps(loc.get("payment_methods", [])),
                json.dumps(loc.get("amenities", [])),
                loc.get("organic", False),
                loc.get("pesticide_free", False),
                loc.get("low_chemical", False),
                loc.get("notes", ""),
                primary_source,
            ),
        )
        location_id = cur.lastrowid
        loc_count += 1

        for crop in loc.get("crops", []):
            cur.execute(
                """
                INSERT INTO crops (
                    location_id, name, is_pyo,
                    season_start_month, season_end_month, notes
                ) VALUES (%s, %s, %s, %s, %s, %s)
                """,
                (
                    location_id,
                    crop.get("name"),
                    crop.get("is_pyo", True),
                    crop.get("season_start_month"),
                    crop.get("season_end_month"),
                    crop.get("notes", ""),
                ),
            )
            crop_count += 1

    conn.commit()
    cur.close()
    conn.close()

    print(f"\n{'='*50}")
    print(f"Inserted {loc_count} locations and {crop_count} crops")
    if skipped:
        print(f"\nSkipped {len(skipped)} locations missing coordinates:")
        for name in skipped:
            print(f"  - {name}")


if __name__ == "__main__":
    main()
