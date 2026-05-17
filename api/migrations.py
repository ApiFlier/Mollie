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
    If it exists, safe-fill any NULL or blank fields with repo values.
    Mollie's edits are preserved."""
    cur.execute(
        "SELECT * FROM locations WHERE LOWER(name) = LOWER(%s)", (name,)
    )
    row = cur.fetchone()
    if row:
        updates = []
        params = []
        fields = [
            ('category_id', category_id),
            ('county', county),
            ('address', address),
            ('city', city),
            ('state', state),
            ('zip', zip_code),
            ('lat', lat),
            ('lng', lng),
            ('website', website),
            ('season_start_month', season_start),
            ('season_end_month', season_end),
            ('notes', notes)
        ]
        for col, repo_val in fields:
            if repo_val is not None and repo_val != "":
                db_val = row.get(col)
                if db_val is None or (isinstance(db_val, str) and db_val.strip() == ""):
                    updates.append(f"{col} = %s")
                    params.append(repo_val)
        if updates:
            params.append(row["id"])
            set_clause = ", ".join(updates)
            cur.execute(
                f"UPDATE locations SET {set_clause} WHERE id = %s",
                tuple(params)
            )
            conn.commit()
            print(f"[migrations]   Safe-filled missing fields for location: {name}")
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


_KEY_V2 = "curated_hiking_trails_butchers_v2"

_HIKING_LOCATIONS_V2 = [
    (
        "Frick Park",
        "Allegheny", "1981 Beechwood Blvd", "Pittsburgh", "PA", "15217",
        40.4398, -79.9168,
        "https://pittsburghparks.org/frick-park",
        3, 11,
        "Large city park with extensive wooded trails. Best in spring through fall; check park conditions before visiting.",
    ),
    (
        "Schenley Park",
        "Allegheny", "500 Panther Hollow Rd", "Pittsburgh", "PA", "15213",
        40.4399, -79.9460,
        "https://pittsburghparks.org/schenley-park",
        3, 11,
        "Urban park offering varied hiking trails and green spaces. Best in spring through fall; check park conditions before visiting.",
    ),
    (
        "Riverview Park",
        "Allegheny", "159 Riverview Ave", "Pittsburgh", "PA", "15214",
        40.4812, -80.0197,
        "https://pittsburghparks.org/riverview-park",
        3, 11,
        "North Side park known for its steep, wooded trails. Best in spring through fall; check park conditions before visiting.",
    ),
    (
        "North Park",
        "Allegheny", "Pearce Mill Rd", "Allison Park", "PA", "15101",
        40.6010, -80.0094,
        "https://www.alleghenycounty.us/parks/north-park",
        3, 11,
        "Expansive county park with diverse trails and a large lake. Best in spring through fall; check park conditions before visiting.",
    ),
    (
        "South Park",
        "Allegheny", "Brownsville Rd", "South Park Township", "PA", "15129",
        40.3134, -80.0105,
        "https://www.alleghenycounty.us/parks/south-park",
        3, 11,
        "Large county park featuring a network of walking trails. Best in spring through fall; check park conditions before visiting.",
    ),
    (
        "Deer Lakes Park",
        "Allegheny", "1090 Bailey Run Rd", "Tarentum", "PA", "15084",
        40.6213, -79.8183,
        "https://www.alleghenycounty.us/parks/deer-lakes-park",
        3, 11,
        "Features trails winding through woods and around lakes. Best in spring through fall; check park conditions before visiting.",
    ),
    (
        "Settlers Cabin Park",
        "Allegheny", "608 Ridge Rd", "Pittsburgh", "PA", "15205",
        40.4217, -80.1444,
        "https://www.alleghenycounty.us/parks/settlers-cabin-park",
        3, 11,
        "Offers trails through rugged and wooded terrain. Best in spring through fall; check park conditions before visiting.",
    ),
    (
        "Round Hill Park",
        "Allegheny", "651 Round Hill Rd", "Elizabeth", "PA", "15037",
        40.2372, -79.8193,
        "https://www.alleghenycounty.us/parks/round-hill-park",
        3, 11,
        "Combines an active farm with scenic walking trails. Best in spring through fall; check park conditions before visiting.",
    ),
    (
        "Montour Trail",
        "Allegheny", "Montour Trail", "Coraopolis", "PA", "15108",
        40.4439, -80.1706,
        "https://montourtrail.org",
        3, 11,
        "Extensive multi-use rail-trail spanning multiple communities. Best in spring through fall; check park conditions before visiting.",
    ),
    (
        "Rachel Carson Trail",
        "Allegheny", "Rachel Carson Trail", "Springdale", "PA", "15144",
        40.5401, -79.7845,
        "https://www.rachelcarsontrails.org",
        3, 11,
        "Challenging, rugged hiking trail stretching across northern Allegheny County. Best in spring through fall; check park conditions before visiting.",
    ),
    (
        "Panhandle Trail",
        "Washington", "Panhandle Trail", "Oakdale", "PA", "15071",
        40.3871, -80.1985,
        "https://panhandletrail.org",
        3, 11,
        "Paved and crushed limestone trail following an old rail line. Best in spring through fall; check park conditions before visiting.",
    ),
    (
        "Roaring Run Trail",
        "Armstrong", "Roaring Run Trail", "Apollo", "PA", "15613",
        40.5699, -79.5539,
        "https://roaringrun.org",
        3, 11,
        "Scenic trail following the Kiskiminetas River. Best in spring through fall; check park conditions before visiting.",
    ),
    (
        "Butler-Freeport Community Trail",
        "Butler", "Butler-Freeport Trail", "Freeport", "PA", "16229",
        40.6756, -79.6841,
        "https://www.butlerfreeporttrail.org",
        3, 11,
        "Rail-trail running through the scenic Buffalo Creek valley. Best in spring through fall; check park conditions before visiting.",
    ),
    (
        "Westmoreland Heritage Trail",
        "Westmoreland", "Westmoreland Heritage Trail", "Trafford", "PA", "15085",
        40.3855, -79.7602,
        "https://westmorelandheritagetrail.com",
        3, 11,
        "Multi-use trail connecting communities in Westmoreland County. Best in spring through fall; check park conditions before visiting.",
    ),
    (
        "Duff Park",
        "Westmoreland", "Duff Park", "Murrysville", "PA", "15668",
        40.4282, -79.6844,
        "https://www.murrysvilleparecreation.com",
        3, 11,
        "Forested park with a network of natural trails. Best in spring through fall; check park conditions before visiting.",
    ),
    (
        "Fall Run Park",
        "Allegheny", "187 Fall Run Rd", "Glenshaw", "PA", "15116",
        40.5348, -79.9575,
        "https://shaler.org",
        3, 11,
        "Features a nature trail leading to a picturesque waterfall. Best in spring through fall; check park conditions before visiting.",
    ),
    (
        "Todd Nature Reserve",
        "Butler", "Keck Rd", "Sarver", "PA", "16055",
        40.7303, -79.7118,
        "https://www.aswp.org",
        3, 11,
        "Audubon Society reserve with secluded, rugged trails. Best in spring through fall; check park conditions before visiting.",
    ),
    (
        "Moraine State Park",
        "Butler", "225 Pleasant Valley Rd", "Portersville", "PA", "16051",
        40.9416, -80.1118,
        "https://www.dcnr.pa.gov",
        3, 11,
        "Large state park offering lakeside and forested trails. Best in spring through fall; check park conditions before visiting.",
    ),
    (
        "Raccoon Creek State Park",
        "Beaver", "3000 State Route 18", "Hookstown", "PA", "15050",
        40.5050, -80.4250,
        "https://www.dcnr.pa.gov",
        3, 11,
        "Features numerous trails exploring a diverse natural landscape. Best in spring through fall; check park conditions before visiting.",
    ),
    (
        "Keystone State Park",
        "Westmoreland", "1150 Keystone Park Rd", "Derry", "PA", "15627",
        40.3750, -79.3780,
        "https://www.dcnr.pa.gov",
        3, 11,
        "State park offering lakeside trails and recreation. Best in spring through fall; check park conditions before visiting.",
    )
]

_BUTCHER_LOCATIONS_V2 = [
    (
        "Tom Friday's Market",
        "Allegheny", "3639 California Ave", "Pittsburgh", "PA", "15212",
        40.4831, -80.0384,
        "https://www.tomfridaysmarket.com",
        None, None,
        "Local butcher/meat market. Check hours before visiting.",
    ),
    (
        "Henry Grasso Inc.",
        "Allegheny", "501 Larimer Ave", "Pittsburgh", "PA", "15206",
        40.4633, -79.9149,
        None,
        None, None,
        "Local butcher/meat market. Check hours before visiting.",
    ),
    (
        "Cheplic Packing",
        "Washington", "370 Spring St", "Finleyville", "PA", "15332",
        40.2450, -79.9961,
        "https://cheplicpacking.com",
        None, None,
        "Local butcher/meat market. Check hours before visiting.",
    ),
    (
        "Lampert's Market",
        "Allegheny", "2101 Penn Ave", "Pittsburgh", "PA", "15222",
        40.4503, -79.9822,
        None,
        None, None,
        "Local butcher/meat market. Check hours before visiting.",
    ),
    (
        "Thoma Meat Market",
        "Butler", "706 Saxonburg Blvd", "Saxonburg", "PA", "16056",
        40.7513, -79.8052,
        "https://thomameat.com",
        None, None,
        "Local butcher/meat market. Check hours before visiting.",
    ),
    (
        "Joe's Butcher Shop",
        "Westmoreland", "101 E Pittsburgh St", "Delmont", "PA", "15626",
        40.4132, -79.5721,
        None,
        None, None,
        "Local butcher/meat market. Check hours before visiting.",
    ),
    (
        "Salem's Halal Market",
        "Allegheny", "2923 Penn Ave", "Pittsburgh", "PA", "15201",
        40.4578, -79.9723,
        "https://salemsmarketgrill.com",
        None, None,
        "Local butcher/meat market. Check hours before visiting.",
    ),
    (
        "Parma Sausage Products",
        "Allegheny", "1734 Penn Ave", "Pittsburgh", "PA", "15222",
        40.4491, -79.9839,
        "https://parmasausage.com",
        None, None,
        "Local butcher/meat market specializing in Italian cured meats. Check hours before visiting.",
    ),
    (
        "DJ's Butcher Block",
        "Allegheny", "4519 Liberty Ave", "Pittsburgh", "PA", "15224",
        40.4630, -79.9525,
        "https://djsbutcherblock.com",
        None, None,
        "Local butcher/meat market. Check hours before visiting.",
    )
]

def _run_v2(conn, cur):
    """Insert expanded hiking-trails/butcher locations for v2."""
    cur.execute(
        "SELECT migration_key FROM app_migrations WHERE migration_key = %s",
        (_KEY_V2,),
    )
    if cur.fetchone():
        return  # already applied

    print(f"[migrations] Running: {_KEY_V2}")

    hiking_id  = _ensure_category(conn, cur, *_HIKING_CATEGORY)
    butcher_id = _ensure_category(conn, cur, *_BUTCHER_CATEGORY)

    for loc in _HIKING_LOCATIONS_V2:
        _ensure_location(conn, cur, loc[0], hiking_id, *loc[1:])
    for loc in _BUTCHER_LOCATIONS_V2:
        _ensure_location(conn, cur, loc[0], butcher_id, *loc[1:])

    cur.execute(
        "INSERT IGNORE INTO app_migrations (migration_key) VALUES (%s)",
        (_KEY_V2,),
    )
    conn.commit()
    print(f"[migrations] Applied: {_KEY_V2}")


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
    _run_v2(conn, cur)
    cur.close()
