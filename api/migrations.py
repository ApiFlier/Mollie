"""
App-level curated-data migrations.

Separate from events.py / _event_migrations, which tracks events-infrastructure
schema changes.  This module handles syncing curated content (categories, locations)
from seed_manifest.json to the live database.
"""

import json
import os

_APP_MIGRATIONS_DDL = (
    "CREATE TABLE IF NOT EXISTS app_migrations ("
    "  migration_key VARCHAR(128) NOT NULL,"
    "  applied_at    DATETIME    NOT NULL DEFAULT CURRENT_TIMESTAMP,"
    "  PRIMARY KEY   (migration_key)"
    ")"
)


def _sync_seed(conn, cur):
    """Sync curated data from seed_manifest.json to the DB."""
    manifest_path = os.path.join(os.path.dirname(__file__), "data", "seed_manifest.json")
    if not os.path.exists(manifest_path):
        print(f"[migrations] Seed manifest not found at {manifest_path}, skipping sync.")
        return

    try:
        with open(manifest_path, "r") as f:
            manifest = json.load(f)
    except Exception as e:
        print(f"[migrations] Failed to read seed manifest: {e}")
        return

    categories = manifest.get("categories", [])
    locations = manifest.get("locations", [])

    stats = {
        "added": 0,
        "updated": 0,
        "skipped_user_modified": 0,
        "soft_removed": 0
    }

    print(f"[migrations] Syncing {len(categories)} categories and {len(locations)} locations from seed manifest...")

    # 1. Sync Categories
    cat_map = {}  # Map LOWER(name) to id
    for c in categories:
        cur.execute("SELECT id FROM categories WHERE LOWER(name) = LOWER(%s)", (c["name"],))
        row = cur.fetchone()
        if row:
            cat_id = row["id"]
        else:
            cur.execute(
                "INSERT INTO categories (name, icon, color, display_order) VALUES (%s, %s, %s, %s)",
                (c.get("name"), c.get("icon"), c.get("color"), c.get("display_order"))
            )
            cat_id = cur.lastrowid
        cat_map[c["name"].lower()] = cat_id

    # 2. Sync Locations
    processed_loc_ids = set()

    for L in locations:
        name = L.get("name")
        if not name:
            continue

        cat_id = cat_map.get(str(L.get("category_name", "")).lower())

        cur.execute("SELECT * FROM locations WHERE LOWER(name) = LOWER(%s)", (name,))
        db_L = cur.fetchone()

        if not db_L:
            # INSERT new seed-managed location
            cols = ["name", "county", "address", "city", "state", "zip", "lat", "lng",
                    "phone", "alt_phone", "fax", "email", "website", "facebook_url",
                    "hours", "event_date", "season_start_month", "season_end_month",
                    "organic", "pesticide_free", "low_chemical", "notes", "source_url"]
            
            cat_id = L.get("category_id")

            vals = [L.get(c) for c in cols]
            payment = json.dumps(L["payment_methods"]) if L.get("payment_methods") else None
            amenities = json.dumps(L["amenities"]) if L.get("amenities") else None

            q_cols = ", ".join(cols + ["category_id", "payment_methods", "amenities", "seed_managed"])
            q_vals = ", ".join(["%s"] * (len(cols) + 3)) + ", TRUE"
            
            cur.execute(f"INSERT INTO locations ({q_cols}) VALUES ({q_vals})", tuple(vals + [cat_id, payment, amenities]))
            processed_loc_ids.add(cur.lastrowid)
            stats["added"] += 1
            print(f"[migrations]   Inserted location: {name}")

        else:
            loc_id = db_L["id"]
            processed_loc_ids.add(loc_id)
            
            is_seed_managed = db_L.get("seed_managed")
            is_user_modified = db_L.get("user_modified")

            if is_seed_managed and not is_user_modified:
                # Fully overwrite with seed manifest data
                cols = ["category_id", "county", "address", "city", "state", "zip", "lat", "lng",
                        "phone", "alt_phone", "fax", "email", "website", "facebook_url",
                        "hours", "event_date", "season_start_month", "season_end_month",
                        "organic", "pesticide_free", "low_chemical", "notes", "source_url"]
                
                updates = [f"{c} = %s" for c in cols]
                params = [L.get(c) for c in cols]
                
                updates.append("payment_methods = %s")
                params.append(json.dumps(L["payment_methods"]) if L.get("payment_methods") else None)
                
                updates.append("amenities = %s")
                params.append(json.dumps(L["amenities"]) if L.get("amenities") else None)
                
                updates.append("hidden = FALSE") # Reactivate if it was hidden

                set_clause = ", ".join(updates)
                cur.execute(f"UPDATE locations SET {set_clause} WHERE id = %s", tuple(params + [loc_id]))
                
                # Treat as updated if we actually updated or if we are securing ownership
                # In sqlite/mysql we might check rowcount, but since we mock we just count it safely
                if getattr(cur, "rowcount", 1) > 0:
                    stats["updated"] += 1

            else:
                if is_user_modified:
                    stats["skipped_user_modified"] += 1
                
                # Safe-fill missing data (user_modified is TRUE, or it wasn't seed_managed before)
                updates = []
                params = []
                fields = [
                    ('category_id', L.get('category_id')),
                    ('county', L.get('county')),
                    ('address', L.get('address')),
                    ('city', L.get('city')),
                    ('state', L.get('state')),
                    ('zip', L.get('zip')),
                    ('lat', L.get('lat')),
                    ('lng', L.get('lng')),
                    ('website', L.get('website')),
                    ('season_start_month', L.get('season_start_month')),
                    ('season_end_month', L.get('season_end_month')),
                    ('notes', L.get('notes'))
                ]
                for col, repo_val in fields:
                    if repo_val is not None and repo_val != "":
                        db_val = db_L.get(col)
                        if db_val is None or (isinstance(db_val, str) and db_val.strip() == ""):
                            updates.append(f"{col} = %s")
                            params.append(repo_val)
                
                if updates:
                    set_clause = ", ".join(updates)
                    cur.execute(f"UPDATE locations SET {set_clause} WHERE id = %s", tuple(params + [loc_id]))
                    if getattr(cur, "rowcount", 1) > 0:
                        stats["updated"] += 1
                    print(f"[migrations]   Safe-filled location: {name}")

            # Always ensure it is marked as seed_managed going forward
            if not is_seed_managed:
                cur.execute("UPDATE locations SET seed_managed = TRUE WHERE id = %s", (loc_id,))

    conn.commit()

    # 3. Soft-hide locations removed from seed
    if processed_loc_ids:
        format_strings = ','.join(['%s'] * len(processed_loc_ids))
        cur.execute(
            f"UPDATE locations SET hidden = TRUE WHERE seed_managed = TRUE AND id NOT IN ({format_strings}) AND hidden = FALSE",
            tuple(processed_loc_ids)
        )
        if getattr(cur, "rowcount", 0) > 0:
            stats["soft_removed"] = cur.rowcount
            print(f"[migrations] Soft-hidden {cur.rowcount} seed-managed locations no longer in manifest.")
        conn.commit()
    
    print(f"[migrations] Seed sync complete: {stats['added']} added rows, {stats['updated']} updated rows, {stats['soft_removed']} soft-removed/deactivated rows, {stats['skipped_user_modified']} skipped user-modified rows.")

def ensure_app_migrations(conn):
    """Create app_migrations table and sync seed data."""
    cur = conn.cursor(dictionary=True)

    cur.execute(_APP_MIGRATIONS_DDL)
    conn.commit()

    # Guard: skip if the main app tables haven't been created yet
    cur.execute("SHOW TABLES LIKE 'categories'")
    if not cur.fetchone():
        print("[migrations] 'categories' table not yet present; skipping data migrations.")
        cur.close()
        return

    cur.execute("SHOW TABLES LIKE 'locations'")
    if not cur.fetchone():
        print("[migrations] 'locations' table not yet present; skipping data migrations.")
        cur.close()
        return

    _sync_seed(conn, cur)
    cur.close()
