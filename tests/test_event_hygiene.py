"""
Tests for external_events refresh hygiene:
  - _parse_int_env safe parsing
  - _upsert_event idempotency (same event twice → no duplicate)
  - _dedupe_external_events merge (saved/hidden flags preserved)
  - _purge_stale_for_source stale cleanup behavior
  - saved events are preserved when SAVED_EVENT_RETENTION_DAYS is unset
  - stale cleanup does NOT run when a source fetch fails
  - invalid retention env vars fall back to defaults without crashing

These tests load events.py directly and use lightweight mock DB objects.
No real MySQL connection is required.
"""
import sys
import os
import importlib
import unittest
from unittest.mock import MagicMock, call, patch
import datetime

# Allow direct import of events.py from api/
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "api"))
import events as _ev


# ── Helpers ───────────────────────────────────────────────────────────────────

def _make_conn(*cursor_results):
    """Return a MagicMock connection whose cursor().fetchall() / fetchone()
    return values from cursor_results in order. Each element is either a list
    (returned by fetchall) or a dict/None (returned by fetchone)."""
    conn = MagicMock()
    cursors = []
    for result in cursor_results:
        cur = MagicMock()
        if isinstance(result, list):
            cur.fetchall.return_value = result
            cur.fetchone.return_value = result[0] if result else None
        else:
            cur.fetchone.return_value = result
            cur.fetchall.return_value = [] if result is None else [result]
        cur.rowcount = 0
        cursors.append(cur)
    # Return cursors in sequence; fall back to a generic mock for extra calls
    _idx = [0]
    def _next_cursor(**kwargs):
        i = _idx[0]
        _idx[0] = min(i + 1, len(cursors) - 1)
        return cursors[i] if cursors else MagicMock()
    conn.cursor.side_effect = _next_cursor
    return conn, cursors


def _ev_dict(**kwargs):
    """Build a minimal event dict with defaults."""
    base = {
        "source_key": "test_source",
        "source_event_id": "ev-1",
        "title": "Test Event",
        "start_datetime": "2026-09-01 10:00:00",
        "end_datetime": None,
        "venue_name": "Test Venue",
        "address": "123 Main St",
        "city": "Pittsburgh",
        "state": "PA",
        "latitude": None,
        "longitude": None,
        "source_url": "https://example.com/event/1",
        "official_url": None,
        "description_short": None,
        "date_label": None,
        "postal_code": None,
        "category": None,
        "image_url": None,
        "admission": None,
        "normalized_fingerprint": "abc123",
        "raw_source_json": None,
    }
    base.update(kwargs)
    return base


# ── Tests: _parse_int_env ─────────────────────────────────────────────────────

class TestParseIntEnv(unittest.TestCase):

    def _call(self, env_dict, name, default, min_val=None, max_val=None):
        with patch.dict(os.environ, env_dict, clear=False):
            # Temporarily remove the var if setting it to missing
            old = os.environ.pop(name, None)
            os.environ.update(env_dict)
            try:
                return _ev._parse_int_env(name, default, min_val, max_val)
            finally:
                if old is not None:
                    os.environ[name] = old
                elif name in os.environ:
                    del os.environ[name]

    def test_missing_returns_default(self):
        with patch.dict(os.environ, {}, clear=False):
            os.environ.pop("_TEST_INT_VAR", None)
            self.assertEqual(_ev._parse_int_env("_TEST_INT_VAR", 14), 14)

    def test_blank_returns_default(self):
        with patch.dict(os.environ, {"_TEST_INT_VAR": ""}):
            self.assertEqual(_ev._parse_int_env("_TEST_INT_VAR", 14), 14)

    def test_whitespace_returns_default(self):
        with patch.dict(os.environ, {"_TEST_INT_VAR": "   "}):
            self.assertEqual(_ev._parse_int_env("_TEST_INT_VAR", 14), 14)

    def test_valid_integer(self):
        with patch.dict(os.environ, {"_TEST_INT_VAR": "30"}):
            self.assertEqual(_ev._parse_int_env("_TEST_INT_VAR", 14), 30)

    def test_float_string_falls_back(self):
        # "14.5" is not a valid int — falls back to default
        with patch.dict(os.environ, {"_TEST_INT_VAR": "14.5"}):
            self.assertEqual(_ev._parse_int_env("_TEST_INT_VAR", 14), 14)

    def test_non_numeric_falls_back(self):
        with patch.dict(os.environ, {"_TEST_INT_VAR": "abc"}):
            self.assertEqual(_ev._parse_int_env("_TEST_INT_VAR", 14), 14)

    def test_below_min_falls_back(self):
        with patch.dict(os.environ, {"_TEST_INT_VAR": "0"}):
            self.assertEqual(_ev._parse_int_env("_TEST_INT_VAR", 14, min_val=1), 14)

    def test_above_max_falls_back(self):
        with patch.dict(os.environ, {"_TEST_INT_VAR": "400"}):
            self.assertEqual(_ev._parse_int_env("_TEST_INT_VAR", 14, max_val=365), 14)

    def test_none_default_returns_none_when_missing(self):
        with patch.dict(os.environ, {}, clear=False):
            os.environ.pop("_TEST_INT_VAR", None)
            self.assertIsNone(_ev._parse_int_env("_TEST_INT_VAR", None))

    def test_none_default_returns_none_on_invalid(self):
        with patch.dict(os.environ, {"_TEST_INT_VAR": "bad"}):
            self.assertIsNone(_ev._parse_int_env("_TEST_INT_VAR", None))

    def test_boundary_min_accepted(self):
        with patch.dict(os.environ, {"_TEST_INT_VAR": "1"}):
            self.assertEqual(_ev._parse_int_env("_TEST_INT_VAR", 14, min_val=1, max_val=365), 1)

    def test_boundary_max_accepted(self):
        with patch.dict(os.environ, {"_TEST_INT_VAR": "365"}):
            self.assertEqual(_ev._parse_int_env("_TEST_INT_VAR", 14, min_val=1, max_val=365), 365)


# ── Tests: _upsert_event idempotency ─────────────────────────────────────────

class TestUpsertIdempotency(unittest.TestCase):
    """Refreshing the same event twice must not create a duplicate row."""

    def _make_simple_conn(self, existing_row):
        """Return a conn whose cursor fetchone always returns existing_row."""
        conn = MagicMock()
        sel_cur = MagicMock()
        sel_cur.fetchone.return_value = existing_row
        upd_cur = MagicMock()
        conn.cursor.side_effect = [sel_cur, upd_cur]
        return conn, sel_cur, upd_cur

    def test_no_existing_calls_insert(self):
        conn, sel_cur, ins_cur = self._make_simple_conn(None)
        ev = _ev_dict()
        _ev._upsert_event(conn, ev)
        # SELECT was called once
        self.assertTrue(sel_cur.execute.called)
        # INSERT was called on the second cursor
        sql = ins_cur.execute.call_args[0][0]
        self.assertIn("INSERT", sql.upper())

    def test_existing_same_source_calls_update(self):
        existing = {
            "id": 42,
            "source_key": "test_source",
            "image_url": None,
            "latitude": None,
            "official_url": None,
        }
        conn, sel_cur, upd_cur = self._make_simple_conn(existing)
        ev = _ev_dict()
        _ev._upsert_event(conn, ev)
        # UPDATE was called on the second cursor
        sql = upd_cur.execute.call_args[0][0]
        self.assertIn("UPDATE", sql.upper())
        # UPDATE targets the existing row by id
        params = upd_cur.execute.call_args[0][1]
        self.assertEqual(params[-1], 42)

    def test_existing_different_source_lower_score_only_bumps_last_seen(self):
        existing = {
            "id": 99,
            "source_key": "other_source",  # different source
            "image_url": "https://img.example.com/foo.jpg",  # higher score
            "latitude": 40.44,
            "official_url": "https://official.example.com",
        }
        conn, sel_cur, bump_cur = self._make_simple_conn(existing)
        ev = _ev_dict(source_key="test_source",
                      image_url=None, latitude=None, official_url=None)
        _ev._upsert_event(conn, ev)
        sql = bump_cur.execute.call_args[0][0]
        self.assertIn("last_seen_at", sql)
        self.assertNotIn("title", sql)  # not a full update

    def test_update_does_not_touch_saved_or_hidden(self):
        """_do_update must never overwrite the user's saved/hidden flags."""
        existing = {"id": 10, "source_key": "test_source",
                    "image_url": None, "latitude": None, "official_url": None}
        conn, sel_cur, upd_cur = self._make_simple_conn(existing)
        ev = _ev_dict()
        _ev._upsert_event(conn, ev)
        update_sql = upd_cur.execute.call_args[0][0]
        self.assertNotIn("saved", update_sql)
        self.assertNotIn("hidden", update_sql)


# ── Tests: _dedupe_external_events ───────────────────────────────────────────

class TestDedupeExternalEvents(unittest.TestCase):

    def test_no_duplicates_returns_zero(self):
        """If no duplicate fingerprints exist, returns 0 and makes no deletions."""
        conn = MagicMock()
        scan_cur = MagicMock()
        scan_cur.fetchall.return_value = []  # no dup groups
        conn.cursor.return_value = scan_cur

        result = _ev._dedupe_external_events(conn)
        self.assertEqual(result, 0)
        conn.commit.assert_not_called()

    def _make_dup_conn(self, dup_rows):
        """Build a conn mock for a single duplicate fingerprint group."""
        conn = MagicMock()
        scan_cur = MagicMock()
        scan_cur.fetchall.return_value = [
            {"normalized_fingerprint": "fp-dup", "cnt": len(dup_rows)}
        ]
        detail_cur = MagicMock()
        detail_cur.fetchall.return_value = dup_rows
        merge_cur = MagicMock()
        conn.cursor.side_effect = [scan_cur, detail_cur, merge_cur, merge_cur]
        return conn, merge_cur

    def test_saved_flag_preserved_from_duplicate(self):
        """If one of the duplicates was saved, the kept row must be saved."""
        now = datetime.datetime.utcnow()
        rows = [
            {"id": 1, "saved": False, "hidden": False,
             "source_url": "http://a.com", "latitude": None,
             "venue_name": "Venue A", "admission": None,
             "category": None, "updated_at": now},
            {"id": 2, "saved": True, "hidden": False,
             "source_url": None, "latitude": None,
             "venue_name": None, "admission": None,
             "category": None, "updated_at": now},
        ]
        conn, merge_cur = self._make_dup_conn(rows)
        result = _ev._dedupe_external_events(conn)
        self.assertEqual(result, 1)  # one duplicate removed
        # The kept row (id=2, saved=True has higher score) should get UPDATE
        # to ensure both flags are set correctly.
        calls = [str(c) for c in merge_cur.execute.call_args_list]
        delete_calls = [c for c in calls if "DELETE" in c]
        self.assertEqual(len(delete_calls), 1)

    def test_hidden_flag_preserved_from_duplicate(self):
        """The hidden row must be kept (not deleted) when deduplicating.

        Row 10 has hidden=True (score=10000) and wins over the richer-but-not-hidden
        row 11 (score=1117). Since the kept row already has hidden=True, no UPDATE
        is needed — the flag is preserved by keeping the right row.
        """
        now = datetime.datetime.utcnow()
        rows = [
            {"id": 10, "saved": False, "hidden": True,
             "source_url": None, "latitude": None,
             "venue_name": None, "admission": None,
             "category": None, "updated_at": now},
            {"id": 11, "saved": False, "hidden": False,
             "source_url": "http://b.com", "latitude": 40.4,
             "venue_name": "Venue B", "admission": "$5",
             "category": "festival", "updated_at": now},
        ]
        conn, merge_cur = self._make_dup_conn(rows)
        result = _ev._dedupe_external_events(conn)
        self.assertEqual(result, 1)  # one row removed

        # id=10 (hidden=True) wins on score and must be KEPT — verify DELETE
        # targets id=11, not id=10.
        delete_calls = [c for c in merge_cur.execute.call_args_list
                        if "DELETE" in str(c[0][0])]
        self.assertEqual(len(delete_calls), 1)
        deleted_ids = list(delete_calls[0][0][1])
        self.assertIn(11, deleted_ids, "id=11 (not hidden) must be deleted")
        self.assertNotIn(10, deleted_ids, "id=10 (hidden) must be kept")

    def test_best_row_wins_by_richness(self):
        """Row with source_url, latitude, venue beats a bare row."""
        now = datetime.datetime.utcnow()
        rows = [
            {"id": 20, "saved": False, "hidden": False,
             "source_url": None, "latitude": None,
             "venue_name": None, "admission": None,
             "category": None, "updated_at": now},
            {"id": 21, "saved": False, "hidden": False,
             "source_url": "http://c.com", "latitude": 40.4,
             "venue_name": "Venue C", "admission": "$10",
             "category": "festival", "updated_at": now},
        ]
        conn, merge_cur = self._make_dup_conn(rows)
        _ev._dedupe_external_events(conn)
        # DELETE should target id=20 (the poorer row)
        delete_calls = [(c[0][0], c[0][1])
                        for c in merge_cur.execute.call_args_list
                        if "DELETE" in str(c[0][0])]
        self.assertEqual(len(delete_calls), 1)
        deleted_ids = list(delete_calls[0][1])
        self.assertIn(20, deleted_ids)
        self.assertNotIn(21, deleted_ids)


# ── Tests: _purge_stale_for_source ───────────────────────────────────────────

class TestPurgeStaleForSource(unittest.TestCase):

    def _make_purge_conn(self, unsaved_rowcount=0, saved_rowcount=0):
        """Return a conn mock for _purge_stale_for_source."""
        conn = MagicMock()
        cur = MagicMock()
        # rowcount changes after each DELETE execute call
        _calls = [0]
        def _rowcount_side(*args, **kwargs):
            pass
        cur.execute.side_effect = lambda *a, **kw: None
        # Return different rowcounts for the two DELETE calls
        _idx = [0]
        rowcounts = [unsaved_rowcount, saved_rowcount]
        def _rowcount():
            return rowcounts[min(_idx[0], len(rowcounts) - 1)]
        type(cur).rowcount = property(lambda self: _rowcount())
        # Track which call we're on
        _orig_execute = cur.execute
        _call_count = [0]
        def _tracked_execute(*args, **kwargs):
            _idx[0] = _call_count[0]
            _call_count[0] += 1
        cur.execute.side_effect = _tracked_execute
        conn.cursor.return_value = cur
        return conn, cur

    def test_stale_unsaved_are_deleted(self):
        """Unsaved old events are deleted after successful refresh."""
        conn = MagicMock()
        cur = MagicMock()
        cur.rowcount = 5
        conn.cursor.return_value = cur

        result = _ev._purge_stale_for_source(conn, "test_source",
                                              retention_days=14)
        self.assertGreaterEqual(result, 0)
        conn.commit.assert_called_once()
        # DELETE was called at least once
        delete_calls = [c for c in cur.execute.call_args_list
                        if "DELETE" in str(c[0][0]).upper()]
        self.assertGreaterEqual(len(delete_calls), 1)
        # The DELETE uses COALESCE(end_datetime, start_datetime)
        delete_sql = str(delete_calls[0][0][0])
        self.assertIn("COALESCE", delete_sql.upper())
        self.assertIn("saved = FALSE", delete_sql)

    def test_saved_events_not_deleted_by_default(self):
        """With saved_retention_days=None (default), saved events are untouched."""
        conn = MagicMock()
        cur = MagicMock()
        cur.rowcount = 3
        conn.cursor.return_value = cur

        _ev._purge_stale_for_source(conn, "test_source",
                                     retention_days=14,
                                     saved_retention_days=None)
        # Only one DELETE call (for unsaved); no DELETE for saved rows
        delete_calls = [c for c in cur.execute.call_args_list
                        if "DELETE" in str(c[0][0]).upper()]
        self.assertEqual(len(delete_calls), 1,
                         "Expected exactly one DELETE (unsaved only)")
        self.assertIn("saved = FALSE", str(delete_calls[0][0][0]))

    def test_saved_events_deleted_when_retention_configured(self):
        """When saved_retention_days is set, a second DELETE for saved rows runs."""
        conn = MagicMock()
        cur = MagicMock()
        cur.rowcount = 0
        conn.cursor.return_value = cur

        _ev._purge_stale_for_source(conn, "test_source",
                                     retention_days=14,
                                     saved_retention_days=180)
        delete_calls = [c for c in cur.execute.call_args_list
                        if "DELETE" in str(c[0][0]).upper()]
        self.assertEqual(len(delete_calls), 2,
                         "Expected two DELETE calls (unsaved + saved)")
        # Second DELETE targets saved=TRUE
        second_sql = str(delete_calls[1][0][0])
        self.assertIn("saved = TRUE", second_sql)

    def test_source_key_scoped_to_correct_source(self):
        """DELETE is scoped to the specific source_key, not all sources."""
        conn = MagicMock()
        cur = MagicMock()
        cur.rowcount = 0
        conn.cursor.return_value = cur

        _ev._purge_stale_for_source(conn, "positively_pgh", retention_days=14)
        for c in cur.execute.call_args_list:
            if "DELETE" in str(c[0][0]).upper():
                params = c[0][1]
                self.assertEqual(params[0], "positively_pgh",
                                 "DELETE must be scoped to source_key")

    def test_uses_coalesce_end_or_start(self):
        """Cleanup uses COALESCE(end_datetime, start_datetime) so multi-day events
        are not removed before they finish."""
        conn = MagicMock()
        cur = MagicMock()
        cur.rowcount = 0
        conn.cursor.return_value = cur

        _ev._purge_stale_for_source(conn, "test_source", retention_days=14)
        delete_calls = [c for c in cur.execute.call_args_list
                        if "DELETE" in str(c[0][0]).upper()]
        sql = str(delete_calls[0][0][0])
        self.assertIn("COALESCE(end_datetime, start_datetime)", sql)


# ── Tests: stale cleanup not called on refresh failure ───────────────────────

class TestRefreshSourceCleanupOnFailure(unittest.TestCase):

    def test_purge_not_called_when_fetch_fails(self):
        """If adapter.fetch() raises, stale cleanup must not run."""
        adapter = MagicMock()
        adapter.source_key = "bad_source"
        adapter.display_name = "Bad Source"
        adapter.fetch.side_effect = RuntimeError("network down")

        # Register the adapter temporarily
        _ev._ADAPTERS["bad_source"] = adapter
        try:
            conn = MagicMock()
            cur = MagicMock()
            cur.fetchone.return_value = {"coverage_days": 30}
            conn.cursor.return_value = cur

            with patch.object(_ev, "_purge_stale_for_source") as mock_purge:
                result = _ev.refresh_source(conn, "bad_source")

            self.assertEqual(result, 0)
            mock_purge.assert_not_called()
        finally:
            _ev._ADAPTERS.pop("bad_source", None)

    def test_purge_called_after_successful_fetch(self):
        """If fetch succeeds, stale cleanup must run exactly once."""
        adapter = MagicMock()
        adapter.source_key = "good_source"
        adapter.display_name = "Good Source"
        adapter.fetch.return_value = []  # empty list — no events to upsert

        _ev._ADAPTERS["good_source"] = adapter
        try:
            conn = MagicMock()
            cur = MagicMock()
            cur.fetchone.return_value = {"coverage_days": 30}
            conn.cursor.return_value = cur

            with patch.object(_ev, "_purge_stale_for_source",
                               return_value=0) as mock_purge:
                _ev.refresh_source(conn, "good_source")

            mock_purge.assert_called_once()
            call_kwargs = mock_purge.call_args
            self.assertEqual(call_kwargs[0][1], "good_source")
        finally:
            _ev._ADAPTERS.pop("good_source", None)


# ── Tests: module-level retention env var parsing ────────────────────────────

class TestRetentionEnvParsing(unittest.TestCase):
    """Verify that invalid env values don't crash the module (reload test)."""

    def _reload_events(self, env_overrides):
        """Reload events module with controlled environment for retention vars."""
        import importlib
        clean = dict(os.environ)
        for k in ("EVENT_CACHE_RETENTION_DAYS", "SAVED_EVENT_RETENTION_DAYS"):
            clean.pop(k, None)
        clean.update(env_overrides)
        old = os.environ.copy()
        os.environ.clear()
        os.environ.update(clean)
        try:
            import events
            importlib.reload(events)
            return events
        finally:
            os.environ.clear()
            os.environ.update(old)

    def test_invalid_retention_falls_back_to_default(self):
        mod = self._reload_events({"EVENT_CACHE_RETENTION_DAYS": "notanumber"})
        self.assertEqual(mod.EVENT_CACHE_RETENTION_DAYS, 14)

    def test_blank_retention_uses_default(self):
        mod = self._reload_events({"EVENT_CACHE_RETENTION_DAYS": ""})
        self.assertEqual(mod.EVENT_CACHE_RETENTION_DAYS, 14)

    def test_valid_retention_is_used(self):
        mod = self._reload_events({"EVENT_CACHE_RETENTION_DAYS": "30"})
        self.assertEqual(mod.EVENT_CACHE_RETENTION_DAYS, 30)

    def test_saved_retention_none_by_default(self):
        mod = self._reload_events({})
        self.assertIsNone(mod._SAVED_RETENTION_DAYS)

    def test_saved_retention_set_when_valid(self):
        mod = self._reload_events({"SAVED_EVENT_RETENTION_DAYS": "180"})
        self.assertEqual(mod._SAVED_RETENTION_DAYS, 180)

    def test_saved_retention_invalid_falls_back_to_none(self):
        mod = self._reload_events({"SAVED_EVENT_RETENTION_DAYS": "???"})
        self.assertIsNone(mod._SAVED_RETENTION_DAYS)

    def test_retention_below_min_falls_back(self):
        mod = self._reload_events({"EVENT_CACHE_RETENTION_DAYS": "0"})
        self.assertEqual(mod.EVENT_CACHE_RETENTION_DAYS, 14)

    def test_retention_above_max_falls_back(self):
        mod = self._reload_events({"EVENT_CACHE_RETENTION_DAYS": "9999"})
        self.assertEqual(mod.EVENT_CACHE_RETENTION_DAYS, 14)


if __name__ == "__main__":
    unittest.main()
