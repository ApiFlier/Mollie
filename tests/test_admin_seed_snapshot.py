"""
Tests for POST /api/admin/seed-snapshot endpoint.

Verifies:
  - unauthenticated requests are rejected with 401
  - authenticated requests call _generate_seed_sql and write seed.sql
  - a backup is created before the seed file is overwritten
  - the response JSON has the expected keys
  - _generate_seed_sql produces valid SQL with required structure
  - _escape_sql_value handles all common Python types

Run with:  python3 -m pytest tests/test_admin_seed_snapshot.py -v
"""
import sys
import os
import types
import importlib.util
import unittest
import unittest.mock
import tempfile
import decimal
import datetime
import json


# ── Stub heavy deps so we can import app.py without Docker ────────────────────

def _stub(name, **attrs):
    m = types.ModuleType(name)
    for k, v in attrs.items():
        setattr(m, k, v)
    sys.modules.setdefault(name, m)
    return sys.modules[name]

_stub("bcrypt")
_stub("flask_cors", CORS=lambda app, **kw: None)
_stub("mysql")
_stub("mysql.connector")
_stub("mysql.connector.pooling")

# Minimal Flask stub
import flask as _flask_real
# We'll use real Flask for proper test client

# Stub heavy adapter imports — each must have the class app.py imports
class _FakeAdapter:
    source_key = "fake"; display_name = "Fake"
    def fetch(self, coverage_days=60): return []

_stub("adapters")
_stub("adapters.positively_pgh",  PositivelyPgh=_FakeAdapter)
_stub("adapters.visit_pittsburgh", VisitPittsburgh=_FakeAdapter)
_stub("adapters.heinz_history",   HeinzHistory=_FakeAdapter)
_stub("adapters.carnegie_museums", CarnegieMuseums=_FakeAdapter)
_stub("adapters.carnegie_library", CarnegieLibrary=_FakeAdapter)
_stub("adapters.wqed_cultural",   WqedCultural=_FakeAdapter)
_stub("adapters.pittsburgh_parks", PittsburghParks=_FakeAdapter)
_stub("adapters.pittsburgh_glass_center", PittsburghGlassCenter=_FakeAdapter)
_stub("adapters.play_pittsburgh", PlayPittsburgh=_FakeAdapter)
_stub("adapters.kidsburgh", Kidsburgh=_FakeAdapter)
_stub("adapters.experience_butler", ExperienceButler=_FakeAdapter)
_stub("adapters.visit_pa", VisitPA=_FakeAdapter)
_stub("adapters.laurel_highlands", LaurelHighlands=_FakeAdapter)
_stub("adapters.pittsburgh_magazine", PittsburghMagazine=_FakeAdapter)
_stub("adapters.mercer_county", MercerCounty=_FakeAdapter)

# Stub events module
_ev_stub = _stub("events")
_ev_stub.register_adapter = lambda a: None
_ev_stub.ensure_tables = lambda c: None
_ev_stub.recalculate_all_distances = lambda c: None
_ev_stub.get_sources = lambda conn, enabled_only=True: []
_ev_stub.make_fingerprint = lambda *a, **kw: "fp"
_ev_stub.make_series_key = lambda *a, **kw: "sk"

_stub("migrations", ensure_app_migrations=lambda c: None)

# Stub requests
_stub("requests")


# ── Load app module ───────────────────────────────────────────────────────────

_APP_PATH = os.path.join(os.path.dirname(__file__), "..", "api", "app.py")
_app_spec = importlib.util.spec_from_file_location("app", _APP_PATH)
_app_mod = importlib.util.module_from_spec(_app_spec)

# Patch pooling before exec
import mysql.connector.pooling as _pooling
_pooling.MySQLConnectionPool = unittest.mock.MagicMock()

_app_spec.loader.exec_module(_app_mod)
app = _app_mod.app
app.config["TESTING"] = True
app.config["SECRET_KEY"] = "test-secret"

_escape_sql_value = _app_mod._escape_sql_value
_generate_seed_sql = _app_mod._generate_seed_sql

# Remove stubs from sys.modules after app is loaded so that other test files
# (test_event_hygiene.py, etc.) can load the real events module without interference.
for _cleanup_key in ["events", "migrations", "requests", "adapters",
                     "adapters.play_pittsburgh", "adapters.kidsburgh",
                     "adapters.experience_butler", "adapters.visit_pa",
                     "adapters.laurel_highlands", "adapters.pittsburgh_magazine",
                     "adapters.mercer_county", "adapters.positively_pgh",
                     "adapters.visit_pittsburgh", "adapters.heinz_history",
                     "adapters.carnegie_museums", "adapters.carnegie_library",
                     "adapters.wqed_cultural", "adapters.pittsburgh_parks",
                     "adapters.pittsburgh_glass_center"]:
    sys.modules.pop(_cleanup_key, None)


# ── Helpers ───────────────────────────────────────────────────────────────────

def _make_conn_mock(tables=None, table_rows=None):
    """Build a minimal mysql.connector connection mock for _generate_seed_sql."""
    tables = tables or ["categories", "locations", "event_sources"]
    table_rows = table_rows or {}

    def _cursor_factory(*args, **kwargs):
        cur = unittest.mock.MagicMock()

        call_count = [0]

        def _execute(sql, *args):
            cur._last_sql = sql

        def _fetchall():
            sql = getattr(cur, "_last_sql", "")
            if "SHOW TABLES" in sql:
                return [(t,) for t in tables]
            if "SHOW CREATE TABLE" in sql:
                table = sql.split("`")[1]
                return [(table, f"CREATE TABLE `{table}` (`id` int NOT NULL)")]
            if sql.startswith("SELECT * FROM"):
                table = sql.split("`")[1]
                rows = table_rows.get(table, [])
                cur.description = [("id",), ("name",)] if rows else [("id",)]
                return rows
            return []

        def _fetchone():
            sql = getattr(cur, "_last_sql", "")
            if "SHOW CREATE TABLE" in sql:
                table = sql.split("`")[1]
                return (table, f"CREATE TABLE `{table}` (`id` int NOT NULL)")
            if "SELECT COUNT" in sql:
                return (0,)
            return None

        cur.execute.side_effect = _execute
        cur.fetchall.side_effect = _fetchall
        cur.fetchone.side_effect = _fetchone
        cur.description = [("id",)]
        return cur

    conn = unittest.mock.MagicMock()
    conn.cursor.side_effect = _cursor_factory
    return conn


# ══════════════════════════════════════════════════════════════════════════════
# _escape_sql_value
# ══════════════════════════════════════════════════════════════════════════════

class TestEscapeSqlValue(unittest.TestCase):
    def test_none(self):
        self.assertEqual(_escape_sql_value(None), "NULL")

    def test_true(self):
        self.assertEqual(_escape_sql_value(True), "1")

    def test_false(self):
        self.assertEqual(_escape_sql_value(False), "0")

    def test_int(self):
        self.assertEqual(_escape_sql_value(42), "42")

    def test_decimal(self):
        self.assertEqual(_escape_sql_value(decimal.Decimal("40.4483000")), "40.4483000")

    def test_datetime(self):
        dt = datetime.datetime(2026, 5, 17, 13, 30, 0)
        self.assertEqual(_escape_sql_value(dt), "'2026-05-17 13:30:00'")

    def test_date(self):
        d = datetime.date(2026, 5, 17)
        self.assertEqual(_escape_sql_value(d), "'2026-05-17'")

    def test_string_plain(self):
        self.assertEqual(_escape_sql_value("hello"), "'hello'")

    def test_string_with_single_quote(self):
        result = _escape_sql_value("it's")
        self.assertIn("\\'", result)
        self.assertNotIn("it's", result)

    def test_string_with_backslash(self):
        result = _escape_sql_value("back\\slash")
        self.assertIn("\\\\", result)

    def test_string_with_newline(self):
        result = _escape_sql_value("line1\nline2")
        self.assertIn("\\n", result)
        self.assertNotIn("\n", result)

    def test_dict_json(self):
        result = _escape_sql_value({"key": "val"})
        self.assertIn("key", result)
        self.assertIn("val", result)
        self.assertTrue(result.startswith("'"))

    def test_empty_string(self):
        self.assertEqual(_escape_sql_value(""), "''")


# ══════════════════════════════════════════════════════════════════════════════
# _generate_seed_sql
# ══════════════════════════════════════════════════════════════════════════════

class TestGenerateSeedSql(unittest.TestCase):
    def _run(self, tables=None, table_rows=None):
        conn = _make_conn_mock(tables, table_rows)
        return _generate_seed_sql(conn)

    def test_returns_string(self):
        sql = self._run()
        self.assertIsInstance(sql, str)

    def test_header_comment_present(self):
        sql = self._run()
        self.assertIn("Event Map", sql)
        self.assertIn("Generated:", sql)
        self.assertIn("PUBLIC GitHub", sql)

    def test_foreign_key_checks_disabled(self):
        sql = self._run()
        self.assertIn("FOREIGN_KEY_CHECKS", sql)

    def test_drop_table_present(self):
        sql = self._run()
        self.assertIn("DROP TABLE IF EXISTS", sql)

    def test_create_table_present(self):
        sql = self._run()
        self.assertIn("CREATE TABLE", sql)

    def test_curated_tables_section(self):
        sql = self._run()
        self.assertIn("Curated baseline data", sql)

    def test_runtime_tables_excluded_from_data(self):
        sql = self._run(tables=["categories", "external_events"])
        self.assertNotIn("INSERT INTO `external_events`", sql)

    def test_insert_generated_for_curated_table(self):
        rows = [(1, "farm")]
        sql = self._run(
            tables=["categories"],
            table_rows={"categories": rows}
        )
        self.assertIn("INSERT INTO `categories`", sql)
        self.assertIn("'farm'", sql)

    def test_event_sources_runtime_reset(self):
        sql = self._run(tables=["event_sources"])
        self.assertIn("UPDATE `event_sources`", sql)
        self.assertIn("last_success_at", sql)
        self.assertIn("NULL", sql)

    def test_no_external_event_user_state_data(self):
        sql = self._run(tables=["external_event_user_state"])
        self.assertNotIn("INSERT INTO `external_event_user_state`", sql)

    def test_no_migration_table_data(self):
        sql = self._run(tables=["_event_migrations"])
        self.assertNotIn("INSERT INTO `_event_migrations`", sql)


# ══════════════════════════════════════════════════════════════════════════════
# /api/admin/seed-snapshot endpoint
# ══════════════════════════════════════════════════════════════════════════════

class TestSeedSnapshotEndpointAuth(unittest.TestCase):
    def setUp(self):
        self.client = app.test_client()

    def test_unauthenticated_returns_401(self):
        resp = self.client.post("/api/admin/seed-snapshot")
        self.assertEqual(resp.status_code, 401)

    def test_get_method_not_allowed_or_not_found(self):
        # Flask may return 405 or 404 for GET on a POST-only route; either is non-200
        with self.client.session_transaction() as sess:
            sess["authenticated"] = True
        resp = self.client.get("/api/admin/seed-snapshot")
        self.assertIn(resp.status_code, (404, 405))


class TestSeedSnapshotEndpointSuccess(unittest.TestCase):
    def setUp(self):
        self.client = app.test_client()
        self._tmpdir_obj = tempfile.TemporaryDirectory()
        self.tmpdir = self._tmpdir_obj.name
        self.seed_file = os.path.join(self.tmpdir, "seed.sql")
        self.backup_dir = os.path.join(self.tmpdir, "backups")
        # Write an existing seed so backup logic runs
        with open(self.seed_file, "w") as f:
            f.write("-- old seed")

    def tearDown(self):
        self._tmpdir_obj.cleanup()

    def _patch_and_call(self, seed_content="-- seed sql"):
        with self.client.session_transaction() as sess:
            sess["authenticated"] = True

        mock_conn = _make_conn_mock()

        with unittest.mock.patch.object(_app_mod, "get_conn", return_value=mock_conn), \
             unittest.mock.patch.object(_app_mod, "_generate_seed_sql", return_value=seed_content), \
             unittest.mock.patch.object(_app_mod, "_SEED_FILE", self.seed_file), \
             unittest.mock.patch.object(_app_mod, "_SEED_BACKUP_DIR", self.backup_dir):
            resp = self.client.post("/api/admin/seed-snapshot")

        data = resp.get_json()
        return resp, data

    def test_authenticated_returns_200(self):
        resp, _ = self._patch_and_call()
        self.assertEqual(resp.status_code, 200)

    def test_response_ok_true(self):
        _, data = self._patch_and_call()
        self.assertTrue(data["ok"])

    def test_response_has_seed_file_key(self):
        _, data = self._patch_and_call()
        self.assertIn("seed_file", data)

    def test_response_has_backup_file_key(self):
        _, data = self._patch_and_call()
        self.assertIn("backup_file", data)
        self.assertIsNotNone(data["backup_file"])

    def test_response_has_counts(self):
        _, data = self._patch_and_call()
        self.assertIn("counts", data)

    def test_response_has_note(self):
        _, data = self._patch_and_call()
        self.assertIn("note", data)
        self.assertIn("publish-seed.sh", data["note"])

    def test_seed_file_written(self):
        seed_content = "-- test seed content"
        self._patch_and_call(seed_content)
        with open(self.seed_file) as f:
            self.assertEqual(f.read(), seed_content)

    def test_backup_created(self):
        self._patch_and_call()
        backups = os.listdir(self.backup_dir)
        self.assertEqual(len(backups), 1)
        self.assertTrue(backups[0].startswith("seed-"))
        self.assertTrue(backups[0].endswith(".sql"))


# ══════════════════════════════════════════════════════════════════════════════
# Hiking-trails schedule support
# ══════════════════════════════════════════════════════════════════════════════

class TestHikingTrailsScheduleInAdmin(unittest.TestCase):
    """admin.js already includes hiking-trails in the schedule section."""

    def _read_admin_js(self):
        path = os.path.join(os.path.dirname(__file__), "..", "admin", "admin.js")
        return open(path).read()

    def test_hiking_trails_in_schedule_section(self):
        js = self._read_admin_js()
        self.assertIn("hiking-trails", js)

    def test_hiking_trails_triggers_schedule_display(self):
        js = self._read_admin_js()
        # The condition controlling the schedule section includes hiking-trails.
        # The condition and the display = "block" assignment are on separate lines,
        # so we verify hiking-trails appears in the same if-block as secSchedule.
        lines = js.splitlines()
        found = False
        for i, line in enumerate(lines):
            if "hiking-trails" in line and ("secSchedule" in line or
               (i + 1 < len(lines) and "secSchedule" in lines[i + 1])):
                found = True
                break
        self.assertTrue(found,
            "hiking-trails should appear in the condition that controls secSchedule visibility")

    def test_publish_seed_sh_exists(self):
        path = os.path.join(os.path.dirname(__file__), "..", "scripts", "commands", "publish-seed.sh")
        self.assertTrue(os.path.exists(path))

    def test_publish_seed_sh_bash_syntax(self):
        import subprocess
        path = os.path.join(os.path.dirname(__file__), "..", "scripts", "commands", "publish-seed.sh")
        result = subprocess.run(["bash", "-n", path], capture_output=True, text=True)
        self.assertEqual(result.returncode, 0, f"bash -n failed: {result.stderr}")

    def test_publish_seed_sh_is_executable(self):
        path = os.path.join(os.path.dirname(__file__), "..", "scripts", "commands", "publish-seed.sh")
        self.assertTrue(os.access(path, os.X_OK))


if __name__ == "__main__":
    unittest.main()
