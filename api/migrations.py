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
        "backfilled": 0,
        "soft_removed": 0,
        "skipped_user_modified": 0
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
    processed_seed_keys = set()

    for L in locations:
        seed_key = L.get("seed_key")
        seed_hash = L.get("seed_hash")
        name = L.get("name")
        
        if not seed_key or not name:
            continue
            
        processed_seed_keys.add(seed_key)

        cat_id = cat_map.get(str(L.get("category_name", "")).lower())

        # Match by seed_key first
        cur.execute("SELECT * FROM locations WHERE seed_key = %s", (seed_key,))
        db_L = cur.fetchone()
        
        # Exact match backfill: fallback to LOWER(name) and category_id if seed_key missing
        if not db_L:
            cur.execute("SELECT * FROM locations WHERE LOWER(name) = LOWER(%s) AND category_id = %s", (name, cat_id))
            db_L = cur.fetchone()
            if db_L:
                # We found it without a seed_key. Backfill seed_key.
                cur.execute("UPDATE locations SET seed_key = %s, seed_managed = TRUE WHERE id = %s", (seed_key, db_L["id"]))
                db_L["seed_key"] = seed_key
                db_L["seed_managed"] = True
                stats["backfilled"] += 1

        if not db_L:
            # INSERT new seed-managed location
            cols = ["name", "county", "address", "city", "state", "zip", "lat", "lng",
                    "website", "season_start_month", "season_end_month", "notes"]
            
            vals = [L.get(c) for c in cols]

            q_cols = ", ".join(cols + ["category_id", "seed_managed", "seed_key", "seed_hash", "hidden"])
            q_vals = ", ".join(["%s"] * (len(cols) + 5))
            
            cur.execute(f"INSERT INTO locations ({q_cols}) VALUES ({q_vals})", tuple(vals + [cat_id, True, seed_key, seed_hash, False]))
            stats["added"] += 1
            print(f"[migrations]   Inserted location: {name}")

        else:
            loc_id = db_L["id"]
            is_user_modified = db_L.get("user_modified")
            current_hash = db_L.get("seed_hash")

            if is_user_modified:
                stats["skipped_user_modified"] += 1
            else:
                if not db_L.get("seed_managed") or current_hash != seed_hash or db_L.get("hidden"):
                    # Fully update managed fields because hash differs (or reactivating)
                    cols = ["name", "county", "address", "city", "state", "zip", "lat", "lng",
                            "website", "season_start_month", "season_end_month", "notes"]
                    
                    updates = [f"{c} = %s" for c in cols]
                    params = [L.get(c) for c in cols]
                    
                    updates.append("category_id = %s")
                    params.append(cat_id)
                    
                    updates.append("seed_key = %s")
                    params.append(seed_key)

                    updates.append("seed_hash = %s")
                    params.append(seed_hash)

                    updates.append("seed_managed = TRUE")
                    updates.append("hidden = FALSE")

                    set_clause = ", ".join(updates)
                    cur.execute(f"UPDATE locations SET {set_clause} WHERE id = %s", tuple(params + [loc_id]))
                    
                    if getattr(cur, "rowcount", 1) > 0:
                        stats["updated"] += 1
                        print(f"[migrations]   Updated location: {name}")

    conn.commit()

    # 3. Soft-hide locations removed from seed
    if processed_seed_keys:
        format_strings = ','.join(['%s'] * len(processed_seed_keys))
        cur.execute(
            f"UPDATE locations SET hidden = TRUE WHERE seed_managed = TRUE AND user_modified = FALSE AND seed_key NOT IN ({format_strings}) AND hidden = FALSE AND seed_key IS NOT NULL",
            tuple(processed_seed_keys)
        )
        if getattr(cur, "rowcount", 0) > 0:
            stats["soft_removed"] = cur.rowcount
            print(f"[migrations] Soft-hidden {cur.rowcount} seed-managed locations no longer in manifest.")
        conn.commit()
    
    print(f"[migrations] Seed sync complete: {stats['added']} added, {stats['updated']} updated, {stats['backfilled']} backfilled, {stats['soft_removed']} soft-removed, {stats['skipped_user_modified']} skipped user-modified.")

_APP_SETTINGS_DDL = (
    "CREATE TABLE IF NOT EXISTS app_settings ("
    "  `key`        VARCHAR(128) NOT NULL,"
    "  `value`      TEXT,"
    "  `updated_at` TIMESTAMP DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,"
    "  PRIMARY KEY (`key`)"
    ")"
)

_APP_SETTINGS_DEFAULTS = [
    ("events.default_date_filter",    "this_weekend"),
    ("events.default_distance_miles", "30"),
    ("events.default_sort",           "soonest"),
    ("events.default_price_filter",   "any"),
    ("events.default_saved_view",     "false"),
    ("map.default_view",              "map"),
    ("map.filters_start_collapsed",   "auto"),
    ("map.default_categories",        "all"),
    ("map.default_month",             ""),
    ("map.default_crop",              ""),
]

def _create_app_settings(conn, cur):
    """Create app_settings table if it does not exist."""
    cur.execute(_APP_SETTINGS_DDL)
    conn.commit()

def _seed_default_settings(conn, cur):
    """Insert factory defaults using INSERT IGNORE — never overwrites user-saved values."""
    for key, value in _APP_SETTINGS_DEFAULTS:
        cur.execute(
            "INSERT IGNORE INTO app_settings (`key`, `value`) VALUES (%s, %s)",
            (key, value)
        )
    conn.commit()
    print("[migrations] app_settings defaults ensured.")

def ensure_app_migrations(conn):
    """Create app_migrations table, create app_settings, and sync seed data."""
    cur = conn.cursor(dictionary=True)

    cur.execute(_APP_MIGRATIONS_DDL)
    conn.commit()

    _create_app_settings(conn, cur)
    _seed_default_settings(conn, cur)

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

    cur.execute("SHOW COLUMNS FROM locations LIKE 'seed_key'")
    if not cur.fetchone():
        print("[migrations] 'seed_key' column not yet present; skipping data migrations.")
        cur.close()
        return

    _sync_seed(conn, cur)
    cur.close()
