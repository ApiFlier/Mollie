"""
App-level curated-data migrations.

Separate from events.py / _event_migrations, which tracks events-infrastructure
schema changes.  This module handles curated content (categories, locations) that
must reach existing production databases after repo updates — without touching
data Mollie has edited and without re-importing the whole seed file.

Each migration is:
  - Tracked by a unique key in the app_migrations table.
  - INSERT-only: never overwrites existing rows.
  - Idempotent: safe to call on every app startup.
  - Guarded: skips gracefully if the core app tables (categories, locations)
    do not exist yet (pre-seed fresh install; they'll be there after seed.sql
    loads and the app restarts).

LIMITATION: The app supports hard-deletion of curated locations (DELETE FROM
locations WHERE id = %s).  There is no tombstone/archive mechanism.  A migration
runs exactly once (tracked key), so if Mollie deletes a seeded location *after*
the migration has already been applied, it will NOT be re-inserted on the next
restart.  If a location is deleted *before* the first migration run it will be
re-inserted.  This is the intended trade-off: one-time catch-up, not continuous
enforcement.
"""

_APP_MIGRATIONS_DDL = (
    "CREATE TABLE IF NOT EXISTS app_migrations ("
    "  migration_key VARCHAR(128) NOT NULL,"
    "  applied_at    DATETIME    NOT NULL DEFAULT CURRENT_TIMESTAMP,"
    "  PRIMARY KEY   (migration_key)"
    ")"
)

# ── Migration v1: hiking-trails + butcher categories and seed locations ────────

_KEY_V1 = "curated_hiking_trails_butchers_v1"

_HIKING_CATEGORY  = ("hiking-trails", "trail",  "#5e9e6e", 57)
_BUTCHER_CATEGORY = ("butcher",       "shop",   "#7f1d1d", 55)

# (name, county, address, city, state, zip, lat, lng, website,
#  season_start_month, season_end_month, notes)
_HIKING_LOCATIONS = [
    (
        "Beechwood Farms Nature Reserve",
        "Allegheny", "614 Dorseyville Road", "Pittsburgh", "PA", "15238",
        40.5338000, -79.9027000,
        "https://www.aswp.org/visit/beechwood-farms-nature-reserve",
        3, 11,
        "Audubon Society of Western PA nature reserve with 9 miles of trails;"
        " dogs on leash welcome on most trails",
    ),
    (
        "Boyce Park",
        "Allegheny", "675 Old Frankstown Road", "Pittsburgh", "PA", "15239",
        40.4433000, -79.8467000,
        "https://www.alleghenycounty.us/parks/boyce-park",
        3, 11,
        "Allegheny County park with hiking trails, ski slopes, and disc golf",
    ),
    (
        "Hartwood Acres Park",
        "Allegheny", "200 Hartwood Acres Drive", "Pittsburgh", "PA", "15238",
        40.5622000, -79.9106000,
        "https://www.alleghenycounty.us/parks/hartwood-acres",
        3, 11,
        "Allegheny County park with wooded hiking trails and historic mansion;"
        " dogs on leash welcome",
    ),
    (
        "Harrison Hills Park",
        "Allegheny", "5200 Freeport Road", "Natrona Heights", "PA", "15065",
        40.6348000, -79.8062000,
        "https://www.alleghenycounty.us/parks/harrison-hills-park",
        3, 11,
        "Allegheny County park along the Allegheny River with challenging ridge"
        " trails and scenic overlooks",
    ),
    (
        "Three Rivers Heritage Trail",
        "Allegheny", None, "Pittsburgh", "PA", None,
        40.4406000, -79.9959000,
        "https://www.friendsoftheriverfront.org/trails/three-rivers-heritage-trail/",
        3, 11,
        "24-mile multi-use trail along the rivers through downtown Pittsburgh;"
        " multiple access points",
    ),
]

_BUTCHER_LOCATIONS = [
    (
        "Strip District Meats",
        "Allegheny", "2121 Penn Avenue", "Pittsburgh", "PA", "15222",
        40.4483000, -79.9799000,
        "https://www.stripdistrictmeats.com",
        None, None,
        "Full-service butcher in the Strip District;"
        " wide selection of fresh and specialty cuts",
    ),
    (
        "Fat Butcher",
        "Allegheny", "5151 Butler Street", "Pittsburgh", "PA", "15201",
        40.4793000, -79.9536000,
        "https://www.fatbutcherpgh.com",
        None, None,
        "Craft butcher shop in Lawrenceville; locally sourced meats and"
        " house-made sausages",
    ),
    (
        "Weiss Meats",
        "Allegheny", "100 Terence Drive", "Pittsburgh", "PA", "15236",
        40.3576000, -79.9862000,
        "https://www.weissmeats.com",
        None, None,
        "Family butcher shop in South Hills; known for house-smoked meats and"
        " homemade products",
    ),
]


def _ensure_category(conn, cur, name, icon, color, display_order):
    """Insert category if missing. Returns its id (existing or new)."""
    cur.execute("SELECT id FROM categories WHERE name = %s", (name,))
    row = cur.fetchone()
    if row:
        return row["id"]
    cur.execute(
        "INSERT INTO categories (name, icon, color, display_order)"
        " VALUES (%s, %s, %s, %s)",
        (name, icon, color, display_order),
    )
    conn.commit()
    print(f"[migrations] Inserted category: {name}")
    return cur.lastrowid


def _ensure_location(conn, cur, name, category_id,
                     county, address, city, state, zip_code,
                     lat, lng, website,
                     season_start, season_end, notes):
    """Insert location if no row with the same name exists.
    Never updates existing rows — Mollie's edits are preserved."""
    cur.execute(
        "SELECT id FROM locations WHERE LOWER(name) = LOWER(%s)", (name,)
    )
    if cur.fetchone():
        return False
    cur.execute(
        "INSERT INTO locations"
        "  (name, category_id, county, address, city, state, zip,"
        "   lat, lng, website, season_start_month, season_end_month, notes)"
        " VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)",
        (name, category_id, county, address, city, state, zip_code,
         lat, lng, website, season_start, season_end, notes),
    )
    conn.commit()
    print(f"[migrations]   Inserted location: {name}")
    return True


def _run_v1(conn, cur):
    """Insert hiking-trails/butcher categories and their seed locations."""
    cur.execute(
        "SELECT migration_key FROM app_migrations WHERE migration_key = %s",
        (_KEY_V1,),
    )
    if cur.fetchone():
        return  # already applied

    print(f"[migrations] Running: {_KEY_V1}")

    hiking_id  = _ensure_category(conn, cur, *_HIKING_CATEGORY)
    butcher_id = _ensure_category(conn, cur, *_BUTCHER_CATEGORY)

    for loc in _HIKING_LOCATIONS:
        _ensure_location(conn, cur, loc[0], hiking_id, *loc[1:])
    for loc in _BUTCHER_LOCATIONS:
        _ensure_location(conn, cur, loc[0], butcher_id, *loc[1:])

    cur.execute(
        "INSERT IGNORE INTO app_migrations (migration_key) VALUES (%s)",
        (_KEY_V1,),
    )
    conn.commit()
    print(f"[migrations] Applied: {_KEY_V1}")


def ensure_app_migrations(conn):
    """Create app_migrations table and run all pending data migrations.

    Safe to call on every startup: idempotent, fast when nothing is pending.
    Skips data migrations if core app tables (categories, locations) are not
    yet present — this happens on a fresh install before seed.sql is loaded.
    The app restarts after seed.sql load and the migration runs as a no-op
    (all rows already present from seed).
    """
    cur = conn.cursor(dictionary=True)

    cur.execute(_APP_MIGRATIONS_DDL)
    conn.commit()

    # Guard: skip if the main app tables haven't been created yet
    cur.execute("SHOW TABLES LIKE 'categories'")
    if not cur.fetchone():
        print("[migrations] 'categories' table not yet present;"
              " skipping data migrations (will retry on next startup).")
        cur.close()
        return

    cur.execute("SHOW TABLES LIKE 'locations'")
    if not cur.fetchone():
        print("[migrations] 'locations' table not yet present;"
              " skipping data migrations (will retry on next startup).")
        cur.close()
        return

    _run_v1(conn, cur)
    cur.close()
