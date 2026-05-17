"""
Tests for api/migrations.py — app-level curated-data migrations.

Verifies:
  - app_migrations table is created
  - first run inserts missing hiking-trails / butcher categories
  - first run inserts all 8 missing seed locations
  - second run is idempotent (no duplicate inserts)
  - existing edited rows are NOT overwritten (INSERT-only, never UPDATE)
  - blank/NULL safe-fill is intentionally absent (existing rows are fully left alone)
  - migration key is recorded in app_migrations after a successful run
  - migration skips gracefully when categories/locations tables don't exist yet
  - custom/user-added locations remain untouched
  - correct categories (hiking-trails + butcher) are referenced for each location group

No real MySQL connection required — uses MagicMock cursors.

Run with:  python3 -m pytest tests/test_app_migrations.py -v
"""
import sys
import os
import unittest
from unittest.mock import MagicMock, call

# Allow direct import of api/ modules without Docker
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "api"))
import migrations as _mg


# ── Cursor/connection factory ─────────────────────────────────────────────────

def _make_cursor(fetchone_seq):
    """Return a MagicMock cursor whose fetchone() returns values from fetchone_seq."""
    cur = MagicMock()
    cur.fetchone.side_effect = list(fetchone_seq)
    cur.lastrowid = 99  # default fake auto-increment id for new INSERT rows
    return cur


def _make_conn(fetchone_seq=()):
    """Return (conn, cursor) where conn.cursor(dictionary=True) returns the cursor."""
    cur = _make_cursor(fetchone_seq)
    conn = MagicMock()
    conn.cursor.return_value = cur
    return conn, cur


# ── Helpers ───────────────────────────────────────────────────────────────────

def _executed_sqls(cur):
    """Return list of SQL strings passed to cur.execute()."""
    return [c.args[0] for c in cur.execute.call_args_list]


def _executed_params(cur):
    """Return list of params tuples passed to cur.execute()."""
    return [c.args[1] if len(c.args) > 1 else c.kwargs.get("args") for c in cur.execute.call_args_list]


def _insert_sqls(cur):
    return [s for s in _executed_sqls(cur) if s.upper().lstrip().startswith("INSERT")]


def _insert_params(cur):
    pairs = [(c.args[0], c.args[1] if len(c.args) > 1 else None)
             for c in cur.execute.call_args_list
             if c.args[0].upper().lstrip().startswith("INSERT")]
    return pairs


# ── Table creation ────────────────────────────────────────────────────────────

class TestAppMigrationsTableCreated(unittest.TestCase):
    """ensure_app_migrations always creates the app_migrations table."""

    def test_ddl_executed_on_call(self):
        # No tables present scenario — guard triggers immediately after DDL
        conn, cur = _make_conn([None])   # SHOW TABLES 'categories' → None
        cur.fetchone.side_effect = [None]
        _mg.ensure_app_migrations(conn)
        sqls = _executed_sqls(cur)
        self.assertTrue(
            any("CREATE TABLE IF NOT EXISTS app_migrations" in s for s in sqls),
            "Expected CREATE TABLE IF NOT EXISTS app_migrations in executed SQL"
        )

    def test_ddl_committed(self):
        conn, cur = _make_conn([None])
        _mg.ensure_app_migrations(conn)
        conn.commit.assert_called()


# ── Guard: tables not yet present ─────────────────────────────────────────────

class TestGuardMissingTables(unittest.TestCase):
    """Migration skips gracefully when core app tables don't exist."""

    def test_skips_when_categories_absent(self):
        # SHOW TABLES 'categories' → None (table missing)
        conn, cur = _make_conn([None])
        _mg.ensure_app_migrations(conn)
        # No INSERT should have happened
        self.assertEqual(_insert_sqls(cur), [],
                         "Should not INSERT anything when categories table is absent")

    def test_skips_when_locations_absent(self):
        # SHOW TABLES 'categories' → present, SHOW TABLES 'locations' → None
        conn, cur = _make_conn([{"Tables_in_db": "categories"}, None])
        _mg.ensure_app_migrations(conn)
        self.assertEqual(_insert_sqls(cur), [],
                         "Should not INSERT anything when locations table is absent")

    def test_cursor_closed_when_categories_absent(self):
        conn, cur = _make_conn([None])
        _mg.ensure_app_migrations(conn)
        cur.close.assert_called_once()

    def test_cursor_closed_when_locations_absent(self):
        conn, cur = _make_conn([{"Tables_in_db": "categories"}, None])
        _mg.ensure_app_migrations(conn)
        cur.close.assert_called_once()


# ── First run: all rows missing ───────────────────────────────────────────────

def _first_run_fetchone():
    """Sequence of fetchone() return values for a pristine DB (nothing exists)."""
    return [
        {"Tables_in_db": "categories"},    # SHOW TABLES 'categories'
        {"Tables_in_db": "locations"},     # SHOW TABLES 'locations'
        None,                              # migration key → not applied
        None,                              # hiking-trails category → missing
        None,                              # butcher category → missing
        None, None, None, None, None,      # 5 hiking locations → all missing
        None, None, None,                  # 3 butcher locations → all missing
    ]


class TestFirstRun(unittest.TestCase):
    """On a pristine DB, the migration inserts all expected rows."""

    def setUp(self):
        self.conn, self.cur = _make_conn(_first_run_fetchone())
        self.cur.lastrowid = 99  # fake category ID after INSERT
        _mg.ensure_app_migrations(self.conn)

    def test_hiking_trails_category_inserted(self):
        params_list = _executed_params(self.cur)
        inserted_names = [
            p[0] for p in params_list
            if isinstance(p, (list, tuple)) and p and p[0] == "hiking-trails"
        ]
        self.assertTrue(
            len(inserted_names) > 0,
            "Expected INSERT for hiking-trails category"
        )

    def test_butcher_category_inserted(self):
        params_list = _executed_params(self.cur)
        inserted_names = [
            p[0] for p in params_list
            if isinstance(p, (list, tuple)) and p and p[0] == "butcher"
        ]
        self.assertTrue(len(inserted_names) > 0, "Expected INSERT for butcher category")

    def test_hiking_trail_locations_inserted(self):
        params_list = _executed_params(self.cur)
        inserted_loc_names = [
            p[0] for p in params_list
            if isinstance(p, (list, tuple)) and len(p) >= 5
            and p[0] in {
                "Beechwood Farms Nature Reserve", "Boyce Park",
                "Hartwood Acres Park", "Harrison Hills Park",
                "Three Rivers Heritage Trail",
            }
        ]
        self.assertEqual(len(inserted_loc_names), 5,
                         f"Expected 5 hiking location inserts, got: {inserted_loc_names}")

    def test_butcher_locations_inserted(self):
        params_list = _executed_params(self.cur)
        inserted_loc_names = [
            p[0] for p in params_list
            if isinstance(p, (list, tuple)) and len(p) >= 5
            and p[0] in {"Strip District Meats", "Fat Butcher", "Weiss Meats"}
        ]
        self.assertEqual(len(inserted_loc_names), 3,
                         f"Expected 3 butcher location inserts, got: {inserted_loc_names}")

    def test_total_insert_count(self):
        # 2 categories + 8 locations + 1 migration key = 11 INSERTs
        inserts = _insert_sqls(self.cur)
        self.assertEqual(len(inserts), 11,
                         f"Expected 11 INSERTs total, got {len(inserts)}: {inserts}")

    def test_migration_key_recorded(self):
        params_list = _executed_params(self.cur)
        migration_inserts = [
            p for p in params_list
            if isinstance(p, (list, tuple)) and len(p) == 1
            and p[0] == _mg._KEY_V1
        ]
        self.assertEqual(len(migration_inserts), 1,
                         "Expected migration key to be recorded in app_migrations")

    def test_hiking_category_color(self):
        """The hiking-trails category must use the soft spring green color."""
        pairs = _insert_params(self.cur)
        for sql, params in pairs:
            if params and params[0] == "hiking-trails":
                self.assertEqual(params[2], "#5e9e6e",
                                 f"hiking-trails color wrong: {params[2]}")
                return
        self.fail("hiking-trails INSERT not found")

    def test_butcher_category_color(self):
        """The butcher category must use the dark red color."""
        pairs = _insert_params(self.cur)
        for sql, params in pairs:
            if params and params[0] == "butcher":
                self.assertEqual(params[2], "#7f1d1d",
                                 f"butcher color wrong: {params[2]}")
                return
        self.fail("butcher INSERT not found")

    def test_hiking_locations_have_season_months(self):
        """All hiking locations should have season_start=3 and season_end=11."""
        pairs = _insert_params(self.cur)
        for sql, params in pairs:
            if (params and len(params) >= 13
                    and params[0] in {
                        "Beechwood Farms Nature Reserve", "Boyce Park",
                        "Hartwood Acres Park", "Harrison Hills Park",
                        "Three Rivers Heritage Trail",
                    }):
                # season_start_month is index 10, season_end_month is index 11
                self.assertEqual(params[10], 3, f"season_start wrong for {params[0]}")
                self.assertEqual(params[11], 11, f"season_end wrong for {params[0]}")

    def test_butcher_locations_have_no_season_months(self):
        """Butcher locations should have NULL season months."""
        pairs = _insert_params(self.cur)
        for sql, params in pairs:
            if (params and len(params) >= 13
                    and params[0] in {"Strip District Meats", "Fat Butcher", "Weiss Meats"}):
                self.assertIsNone(params[10], f"season_start should be None for {params[0]}")
                self.assertIsNone(params[11], f"season_end should be None for {params[0]}")


# ── Second run: idempotency ───────────────────────────────────────────────────

class TestIdempotency(unittest.TestCase):
    """Second run (migration key already in table) does nothing."""

    def setUp(self):
        conn, cur = _make_conn([
            {"Tables_in_db": "categories"},   # SHOW TABLES 'categories'
            {"Tables_in_db": "locations"},    # SHOW TABLES 'locations'
            {"migration_key": _mg._KEY_V1},   # migration already applied
        ])
        _mg.ensure_app_migrations(conn)
        self.cur = cur

    def test_no_inserts_on_second_run(self):
        inserts = _insert_sqls(self.cur)
        self.assertEqual(inserts, [],
                         f"Expected no INSERTs on second run, got: {inserts}")

    def test_no_categories_inserted(self):
        params_list = _executed_params(self.cur)
        cat_inserts = [
            p for p in params_list
            if isinstance(p, (list, tuple))
            and p and p[0] in ("hiking-trails", "butcher")
        ]
        self.assertEqual(cat_inserts, [])

    def test_commit_only_for_ddl(self):
        # commit() is called once (after CREATE TABLE app_migrations DDL)
        self.assertEqual(self.conn.commit.call_count, 1)


# ── Existing rows not overwritten ─────────────────────────────────────────────

class TestExistingRowsPreserved(unittest.TestCase):
    """INSERT-only: existing categories and locations are never updated."""

    def test_existing_hiking_category_not_overwritten(self):
        """If hiking-trails category already exists, no INSERT is issued for it."""
        conn, cur = _make_conn([
            {"Tables_in_db": "categories"},
            {"Tables_in_db": "locations"},
            None,                          # migration not applied
            {"id": 9},                     # hiking-trails EXISTS
            None,                          # butcher missing
            # all 8 locations missing
            None, None, None, None, None,
            None, None, None,
        ])
        cur.lastrowid = 55
        _mg.ensure_app_migrations(conn)
        pairs = _insert_params(cur)
        cat_inserts = [p for s, p in pairs if p and p[0] == "hiking-trails"]
        self.assertEqual(cat_inserts, [],
                         "hiking-trails INSERT should not occur when category exists")

    def test_existing_location_not_overwritten(self):
        """If a location already exists (by name), no INSERT is issued for it."""
        # "Boyce Park" already exists — its fetchone returns a row
        # Build the sequence: categories both exist, migration not applied,
        # then location checks: only Boyce Park returns a row; rest are None.
        conn, cur = _make_conn([
            {"Tables_in_db": "categories"},
            {"Tables_in_db": "locations"},
            None,                          # migration not applied
            {"id": 9},                     # hiking-trails exists
            {"id": 8},                     # butcher exists
            None,                          # Beechwood → insert
            {"id": 742},                   # Boyce Park → EXISTS, skip
            None,                          # Hartwood → insert
            None,                          # Harrison Hills → insert
            None,                          # Three Rivers → insert
            None,                          # Strip District → insert
            None,                          # Fat Butcher → insert
            None,                          # Weiss Meats → insert
        ])
        cur.lastrowid = 800
        _mg.ensure_app_migrations(conn)
        pairs = _insert_params(cur)
        boyce_inserts = [p for s, p in pairs if p and p[0] == "Boyce Park"]
        self.assertEqual(boyce_inserts, [],
                         "Boyce Park should not be INSERT-ed when it already exists")

    def test_existing_location_notes_not_changed(self):
        """No UPDATE is ever issued, even if an existing row has different notes."""
        conn, cur = _make_conn([
            {"Tables_in_db": "categories"},
            {"Tables_in_db": "locations"},
            None,
            {"id": 9},   # both categories present
            {"id": 8},
            # all 8 locations already present
            {"id": 741}, {"id": 742}, {"id": 743}, {"id": 744}, {"id": 745},
            {"id": 746}, {"id": 747}, {"id": 748},
        ])
        _mg.ensure_app_migrations(conn)
        update_sqls = [s for s in _executed_sqls(cur)
                       if s.upper().lstrip().startswith("UPDATE")]
        self.assertEqual(update_sqls, [],
                         "No UPDATE should ever be issued — Mollie's edits are preserved")

    def test_no_safe_fill_when_row_exists(self):
        """blank/NULL safe-fill is intentionally absent: existing rows are left completely alone."""
        # Scenario: all rows exist — migration should issue zero data-mutating statements
        conn, cur = _make_conn([
            {"Tables_in_db": "categories"},
            {"Tables_in_db": "locations"},
            None,
            {"id": 9}, {"id": 8},
            {"id": 741}, {"id": 742}, {"id": 743}, {"id": 744}, {"id": 745},
            {"id": 746}, {"id": 747}, {"id": 748},
        ])
        _mg.ensure_app_migrations(conn)
        data_mutating = [
            s for s in _executed_sqls(cur)
            if s.upper().lstrip().startswith(("INSERT INTO categories",
                                               "INSERT INTO locations",
                                               "UPDATE"))
        ]
        self.assertEqual(data_mutating, [],
                         "Should not mutate any data when all rows already exist")


# ── Migration key recorded ────────────────────────────────────────────────────

class TestMigrationKeyRecorded(unittest.TestCase):

    def test_key_is_correct_string(self):
        self.assertEqual(_mg._KEY_V1, "curated_hiking_trails_butchers_v1")

    def test_key_inserted_after_successful_run(self):
        conn, cur = _make_conn(_first_run_fetchone())
        cur.lastrowid = 99
        _mg.ensure_app_migrations(conn)
        pairs = _insert_params(cur)
        migration_key_inserts = [
            p for s, p in pairs
            if "app_migrations" in s and p and p[0] == _mg._KEY_V1
        ]
        self.assertEqual(len(migration_key_inserts), 1)

    def test_key_not_inserted_when_already_applied(self):
        conn, cur = _make_conn([
            {"Tables_in_db": "categories"},
            {"Tables_in_db": "locations"},
            {"migration_key": _mg._KEY_V1},
        ])
        _mg.ensure_app_migrations(conn)
        pairs = _insert_params(cur)
        migration_inserts = [p for s, p in pairs if "app_migrations" in s]
        self.assertEqual(migration_inserts, [],
                         "Should not re-record key when migration already applied")


# ── Custom user data untouched ────────────────────────────────────────────────

class TestCustomUserDataUntouched(unittest.TestCase):
    """User-created locations (non-seed names) are never affected."""

    def test_user_location_not_touched(self):
        """A user-added location with a unique name that doesn't match any seed name
        is never part of the INSERT statements issued by the migration."""
        conn, cur = _make_conn(_first_run_fetchone())
        cur.lastrowid = 99
        _mg.ensure_app_migrations(conn)
        pairs = _insert_params(cur)
        user_loc_inserts = [
            p for s, p in pairs
            if isinstance(p, (list, tuple))
            and p and p[0] == "Mollie's Secret Farm Stand"
        ]
        self.assertEqual(user_loc_inserts, [],
                         "User-created locations should never appear in migration INSERTs")

    def test_migration_only_touches_named_seed_locations(self):
        """Only the 8 expected seed locations are ever INSERT-candidates."""
        expected_names = {
            "Beechwood Farms Nature Reserve", "Boyce Park",
            "Hartwood Acres Park", "Harrison Hills Park",
            "Three Rivers Heritage Trail",
            "Strip District Meats", "Fat Butcher", "Weiss Meats",
        }
        conn, cur = _make_conn(_first_run_fetchone())
        cur.lastrowid = 99
        _mg.ensure_app_migrations(conn)
        pairs = _insert_params(cur)
        # Filter for location INSERTs (13-param tuple: name, cat_id, county, ...)
        loc_inserts = [
            p[0] for s, p in pairs
            if "INSERT INTO locations" in s and p
        ]
        for name in loc_inserts:
            self.assertIn(name, expected_names,
                          f"Unexpected location INSERT: {name!r}")


# ── Module constants sanity check ─────────────────────────────────────────────

class TestMigrationConstants(unittest.TestCase):

    def test_hiking_locations_count(self):
        self.assertEqual(len(_mg._HIKING_LOCATIONS), 5)

    def test_butcher_locations_count(self):
        self.assertEqual(len(_mg._BUTCHER_LOCATIONS), 3)

    def test_hiking_category_slug(self):
        self.assertEqual(_mg._HIKING_CATEGORY[0], "hiking-trails")

    def test_butcher_category_slug(self):
        self.assertEqual(_mg._BUTCHER_CATEGORY[0], "butcher")

    def test_hiking_category_color(self):
        self.assertEqual(_mg._HIKING_CATEGORY[2], "#5e9e6e")

    def test_butcher_category_color(self):
        self.assertEqual(_mg._BUTCHER_CATEGORY[2], "#7f1d1d")

    def test_hiking_location_names(self):
        names = {loc[0] for loc in _mg._HIKING_LOCATIONS}
        self.assertIn("Beechwood Farms Nature Reserve", names)
        self.assertIn("Three Rivers Heritage Trail", names)

    def test_butcher_location_names(self):
        names = {loc[0] for loc in _mg._BUTCHER_LOCATIONS}
        self.assertIn("Strip District Meats", names)
        self.assertIn("Fat Butcher", names)
        self.assertIn("Weiss Meats", names)

    def test_all_hiking_locations_have_season_months(self):
        for loc in _mg._HIKING_LOCATIONS:
            self.assertEqual(loc[9], 3,  f"season_start wrong for {loc[0]}")
            self.assertEqual(loc[10], 11, f"season_end wrong for {loc[0]}")

    def test_butcher_locations_have_null_season_months(self):
        for loc in _mg._BUTCHER_LOCATIONS:
            self.assertIsNone(loc[9],  f"season_start should be None for {loc[0]}")
            self.assertIsNone(loc[10], f"season_end should be None for {loc[0]}")


if __name__ == "__main__":
    unittest.main()
