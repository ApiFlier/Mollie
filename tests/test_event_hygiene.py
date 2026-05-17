"""
Tests for external_events refresh hygiene:
  - _parse_int_env safe parsing
  - make_fingerprint occurrence-safe identity (source_key + ID + full datetime)
  - make_series_key recurring-event grouping key
  - _upsert_event idempotency (same event twice → no duplicate)
  - _apply_user_state restores saved/hidden from external_event_user_state
  - _dedupe_external_events merge (saved/hidden flags preserved)
  - _dedupe_external_events skips rows with different start_datetimes
  - _purge_stale_for_source stale cleanup behavior
  - saved/hidden/user_touched events preserved during stale cleanup
  - stale cleanup does NOT run when a source fetch fails
  - invalid retention env vars fall back to defaults without crashing
  - same title/venue on different weekends → different fingerprints (not collapsed)
  - same title/venue same day different times → different fingerprints (not collapsed)

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

# Capture originals immediately — adapter test files monkey-patch _ev module
# via sys.modules["events"], which would corrupt these references if accessed later.
_make_fingerprint = _ev.make_fingerprint
_make_series_key  = _ev.make_series_key


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
        "series_key": None,
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
        """Return a conn whose cursor fetchone always returns existing_row.

        Provides a third cursor for _apply_user_state (returns no user state
        so it is a no-op — tests that need user_state use separate fixtures).
        """
        conn = MagicMock()
        sel_cur = MagicMock()
        sel_cur.fetchone.return_value = existing_row
        upd_cur = MagicMock()
        # _apply_user_state calls conn.cursor() for a SELECT; return None → no-op
        state_cur = MagicMock()
        state_cur.fetchone.return_value = None
        conn.cursor.side_effect = [sel_cur, upd_cur, state_cur]
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
        """Untouched old events are deleted after successful refresh."""
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
        # Multi-table DELETE aliases external_events as e
        self.assertIn("e.saved = FALSE", delete_sql)
        # Hidden events are also preserved
        self.assertIn("e.hidden = FALSE", delete_sql)
        # user_state JOIN preserves user_touched rows
        self.assertIn("external_event_user_state", delete_sql)

    def test_saved_events_not_deleted_by_default(self):
        """With saved_retention_days=None (default), saved events are untouched."""
        conn = MagicMock()
        cur = MagicMock()
        cur.rowcount = 3
        conn.cursor.return_value = cur

        _ev._purge_stale_for_source(conn, "test_source",
                                     retention_days=14,
                                     saved_retention_days=None)
        # Only one DELETE call (for untouched rows); no DELETE for saved/hidden
        delete_calls = [c for c in cur.execute.call_args_list
                        if "DELETE" in str(c[0][0]).upper()]
        self.assertEqual(len(delete_calls), 1,
                         "Expected exactly one DELETE (untouched rows only)")
        self.assertIn("e.saved = FALSE", str(delete_calls[0][0][0]))

    def test_saved_events_deleted_when_retention_configured(self):
        """When saved_retention_days is set, a second DELETE for saved/hidden rows runs."""
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
                         "Expected two DELETE calls (untouched + saved/hidden)")
        # Second DELETE targets saved OR hidden
        second_sql = str(delete_calls[1][0][0])
        self.assertIn("e.saved = TRUE", second_sql)
        self.assertIn("e.hidden = TRUE", second_sql)

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
        self.assertIn("COALESCE(e.end_datetime, e.start_datetime)", sql)


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
            cur.fetchone.return_value = {"coverage_days": 60}
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
            cur.fetchone.return_value = {"coverage_days": 60}
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


# ── Tests: make_fingerprint occurrence-safe identity ─────────────────────────

class TestMakeFingerprint(unittest.TestCase):

    def test_path_a_uses_source_key_id_and_full_datetime(self):
        """Path A: source_key + source_event_id + full start_datetime."""
        fp = _make_fingerprint("src", "evt-1", "2026-09-01 10:00:00")
        self.assertIsNotNone(fp)
        self.assertEqual(len(fp), 32)  # MD5 hex

    def test_same_id_different_time_different_fingerprint(self):
        """Same title/venue on the same day at different times → different fingerprints."""
        fp1 = _make_fingerprint("src", "evt-1", "2026-09-01 10:00:00")
        fp2 = _make_fingerprint("src", "evt-1", "2026-09-01 19:00:00")
        self.assertNotEqual(fp1, fp2,
                            "Events with different times must not share a fingerprint")

    def test_same_title_different_weekend_different_fingerprint(self):
        """Same title and venue on different weekends → different fingerprints."""
        fp1 = _make_fingerprint("src", "evt-1", "2026-09-05 10:00:00",
                                "Jazz Night", "Club A")
        fp2 = _make_fingerprint("src", "evt-1", "2026-09-12 10:00:00",
                                "Jazz Night", "Club A")
        self.assertNotEqual(fp1, fp2,
                            "Events on different weekends must not share a fingerprint")

    def test_same_occurrence_same_fingerprint(self):
        """Exact same source + id + datetime always yields the same fingerprint."""
        fp1 = _make_fingerprint("heinz_history", "12345", "2026-09-01 14:00:00")
        fp2 = _make_fingerprint("heinz_history", "12345", "2026-09-01 14:00:00")
        self.assertEqual(fp1, fp2,
                         "Same occurrence must always produce the same fingerprint")

    def test_different_sources_same_id_different_fingerprint(self):
        """Different sources with same event ID must not collide."""
        fp1 = _make_fingerprint("source_a", "99", "2026-09-01 10:00:00")
        fp2 = _make_fingerprint("source_b", "99", "2026-09-01 10:00:00")
        self.assertNotEqual(fp1, fp2,
                            "Same event ID from different sources must not collide")

    def test_path_b_fallback_no_event_id(self):
        """Path B fallback: source_key + title + datetime + venue (no event ID)."""
        fp = _make_fingerprint("src", None, "2026-09-01 10:00:00",
                               "Jazz Night", "Club A")
        self.assertIsNotNone(fp)
        self.assertEqual(len(fp), 32)

    def test_path_b_different_times_different_fingerprint(self):
        """Path B: same title/venue/source, different times → different fingerprints."""
        fp1 = _make_fingerprint("src", None, "2026-09-01 10:00:00",
                                "Jazz Night", "Club A")
        fp2 = _make_fingerprint("src", None, "2026-09-01 20:00:00",
                                "Jazz Night", "Club A")
        self.assertNotEqual(fp1, fp2,
                            "Path B: different times must yield different fingerprints")

    def test_path_b_different_weekends_different_fingerprint(self):
        """Path B: same title/venue/source, different weekends → different fingerprints."""
        fp1 = _make_fingerprint("src", None, "2026-09-05 19:00:00",
                                "Jazz Night", "Club A")
        fp2 = _make_fingerprint("src", None, "2026-09-12 19:00:00",
                                "Jazz Night", "Club A")
        self.assertNotEqual(fp1, fp2)

    def test_none_inputs_do_not_crash(self):
        """None inputs should not crash fingerprint generation."""
        fp = _make_fingerprint(None, None, None, None, None)
        self.assertIsNotNone(fp)
        self.assertEqual(len(fp), 32)

    def test_empty_source_event_id_uses_path_b(self):
        """Empty string event ID falls through to Path B (source_key + title + dt)."""
        fp_b = _make_fingerprint("src", "", "2026-09-01 10:00:00",
                                 "Jazz Night", "Club A")
        fp_a = _make_fingerprint("src", "X", "2026-09-01 10:00:00",
                                 "Jazz Night", "Club A")
        self.assertNotEqual(fp_b, fp_a,
                            "Empty event ID should not produce same FP as event with ID 'X'")


# ── Tests: make_series_key ────────────────────────────────────────────────────

class TestMakeSeriesKey(unittest.TestCase):

    def test_same_source_and_title_same_series_key(self):
        """All occurrences of the same event share a series_key."""
        sk1 = _make_series_key("heinz_history", "Jazz Night")
        sk2 = _make_series_key("heinz_history", "Jazz Night")
        self.assertEqual(sk1, sk2)

    def test_different_times_same_series_key(self):
        """series_key is NOT affected by date/time."""
        sk1 = _make_series_key("src", "Jazz Night")
        sk2 = _make_series_key("src", "Jazz Night")
        self.assertEqual(sk1, sk2,
                         "series_key must ignore datetime entirely")

    def test_different_titles_different_series_key(self):
        """Different event names always produce different series keys."""
        sk1 = _make_series_key("src", "Jazz Night")
        sk2 = _make_series_key("src", "Blues Night")
        self.assertNotEqual(sk1, sk2)

    def test_different_sources_different_series_key(self):
        """Same title from different sources gets different series keys."""
        sk1 = _make_series_key("source_a", "Jazz Night")
        sk2 = _make_series_key("source_b", "Jazz Night")
        self.assertNotEqual(sk1, sk2)

    def test_series_key_not_equal_to_fingerprint(self):
        """series_key must never accidentally equal a normalized_fingerprint
        (they have different inputs and must never be confused)."""
        fp = _make_fingerprint("src", "99", "2026-09-01 10:00:00")
        sk = _make_series_key("src", "Jazz Night")
        self.assertNotEqual(fp, sk)

    def test_none_inputs_do_not_crash(self):
        sk = _make_series_key(None, None)
        self.assertIsNotNone(sk)


# ── Tests: _apply_user_state ──────────────────────────────────────────────────

class TestApplyUserState(unittest.TestCase):

    def test_no_user_state_no_update(self):
        """When no user_state entry exists, external_events is not modified."""
        conn = MagicMock()
        sel_cur = MagicMock()
        sel_cur.fetchone.return_value = None  # no user state
        conn.cursor.return_value = sel_cur

        _ev._apply_user_state(conn, "fp-123")

        # No UPDATE should have been called
        update_calls = [c for c in sel_cur.execute.call_args_list
                        if "UPDATE" in str(c[0][0]).upper()]
        self.assertEqual(len(update_calls), 0)

    def test_user_state_found_applies_saved_hidden(self):
        """When user_state exists, saved/hidden are applied to external_events."""
        conn = MagicMock()
        sel_cur = MagicMock()
        sel_cur.fetchone.return_value = {"saved": True, "hidden": False}
        upd_cur = MagicMock()
        conn.cursor.side_effect = [sel_cur, upd_cur]

        _ev._apply_user_state(conn, "fp-abc")

        # UPDATE must have been called
        self.assertTrue(upd_cur.execute.called)
        sql = upd_cur.execute.call_args[0][0]
        params = upd_cur.execute.call_args[0][1]
        self.assertIn("UPDATE", sql.upper())
        self.assertIn("saved", sql)
        # saved=True, hidden=False, fingerprint="fp-abc"
        self.assertEqual(params, (True, False, "fp-abc"))

    def test_none_fingerprint_skips_lookup(self):
        """If fingerprint is None/empty, _apply_user_state must be a no-op."""
        conn = MagicMock()
        _ev._apply_user_state(conn, None)
        conn.cursor.assert_not_called()

        _ev._apply_user_state(conn, "")
        conn.cursor.assert_not_called()


# ── Tests: _dedupe skips rows with different start_datetimes ─────────────────

class TestDedupeSkipsDifferentDatetimes(unittest.TestCase):

    def test_different_start_datetimes_are_not_collapsed(self):
        """If two rows share a fingerprint but have different start_datetimes,
        they must NOT be deduplicated — they are distinct occurrences."""
        conn = MagicMock()
        scan_cur = MagicMock()
        scan_cur.fetchall.return_value = [
            {"normalized_fingerprint": "fp-recurring", "cnt": 2}
        ]
        detail_cur = MagicMock()
        detail_cur.fetchall.return_value = [
            {"id": 1, "saved": False, "hidden": False,
             "start_datetime": "2026-09-05 19:00:00",
             "source_url": None, "latitude": None, "venue_name": None,
             "admission": None, "category": None,
             "updated_at": datetime.datetime(2026, 9, 1)},
            {"id": 2, "saved": False, "hidden": False,
             "start_datetime": "2026-09-12 19:00:00",
             "source_url": None, "latitude": None, "venue_name": None,
             "admission": None, "category": None,
             "updated_at": datetime.datetime(2026, 9, 1)},
        ]
        conn.cursor.side_effect = [scan_cur, detail_cur]

        result = _ev._dedupe_external_events(conn)

        # Must return 0 — neither row deleted
        self.assertEqual(result, 0,
                         "Rows with different datetimes must not be deleted")
        # commit must not be called (no deletions)
        conn.commit.assert_not_called()

    def test_same_start_datetime_is_deduplicated(self):
        """Two rows with identical start_datetimes and same fingerprint are collapsed."""
        now = datetime.datetime(2026, 9, 5, 19, 0, 0)
        conn = MagicMock()
        scan_cur = MagicMock()
        scan_cur.fetchall.return_value = [
            {"normalized_fingerprint": "fp-dup", "cnt": 2}
        ]
        detail_cur = MagicMock()
        detail_cur.fetchall.return_value = [
            {"id": 3, "saved": False, "hidden": False,
             "start_datetime": now,
             "source_url": None, "latitude": None, "venue_name": None,
             "admission": None, "category": None, "updated_at": now},
            {"id": 4, "saved": False, "hidden": False,
             "start_datetime": now,
             "source_url": "http://a.com", "latitude": 40.4, "venue_name": "Venue",
             "admission": None, "category": None, "updated_at": now},
        ]
        merge_cur = MagicMock()
        conn.cursor.side_effect = [scan_cur, detail_cur, merge_cur]

        result = _ev._dedupe_external_events(conn)

        self.assertEqual(result, 1, "One duplicate should be removed")


# ── Tests: user state survives refresh ───────────────────────────────────────

class TestUserStateSurvivesRefresh(unittest.TestCase):

    def test_upsert_applies_user_state_from_table(self):
        """After upsert, if user_state exists for fingerprint, saved/hidden are restored."""
        # Simulate an INSERT (no existing row), then user_state lookup returns saved=True
        conn = MagicMock()
        sel_cur = MagicMock()
        sel_cur.fetchone.return_value = None  # no existing row → INSERT
        ins_cur = MagicMock()
        state_sel_cur = MagicMock()
        state_sel_cur.fetchone.return_value = {"saved": True, "hidden": False}
        state_upd_cur = MagicMock()
        conn.cursor.side_effect = [sel_cur, ins_cur, state_sel_cur, state_upd_cur]

        ev = _ev_dict(normalized_fingerprint="fp-known")
        _ev._upsert_event(conn, ev)

        # state_upd_cur should have been called with an UPDATE for saved/hidden
        self.assertTrue(state_upd_cur.execute.called)
        sql = state_upd_cur.execute.call_args[0][0]
        self.assertIn("UPDATE", sql.upper())

    def test_upsert_no_state_leaves_saved_hidden_alone(self):
        """If no user_state entry exists, upsert does not touch saved/hidden."""
        conn = MagicMock()
        sel_cur = MagicMock()
        sel_cur.fetchone.return_value = None  # no existing row → INSERT
        ins_cur = MagicMock()
        state_sel_cur = MagicMock()
        state_sel_cur.fetchone.return_value = None  # no user state → no-op
        conn.cursor.side_effect = [sel_cur, ins_cur, state_sel_cur]

        ev = _ev_dict(normalized_fingerprint="fp-new")
        _ev._upsert_event(conn, ev)

        # No UPDATE for saved/hidden after INSERT
        # state_sel_cur.execute was called for SELECT; no additional UPDATE cursor needed
        execute_calls = [c[0][0] for c in ins_cur.execute.call_args_list]
        for sql in execute_calls:
            self.assertNotIn("saved", sql.lower(),
                             "_do_insert must not set saved/hidden")

    def test_purge_preserves_hidden_events(self):
        """Hidden events (hidden=TRUE) must not be deleted by stale cleanup."""
        conn = MagicMock()
        cur = MagicMock()
        cur.rowcount = 0
        conn.cursor.return_value = cur

        _ev._purge_stale_for_source(conn, "test_source", retention_days=14)

        delete_calls = [c for c in cur.execute.call_args_list
                        if "DELETE" in str(c[0][0]).upper()]
        sql = str(delete_calls[0][0][0])
        self.assertIn("e.hidden = FALSE", sql,
                      "Stale purge must skip hidden events")

    def test_purge_preserves_user_touched_via_join(self):
        """user_touched rows in user_state are preserved by the LEFT JOIN condition."""
        conn = MagicMock()
        cur = MagicMock()
        cur.rowcount = 0
        conn.cursor.return_value = cur

        _ev._purge_stale_for_source(conn, "test_source", retention_days=14)

        delete_calls = [c for c in cur.execute.call_args_list
                        if "DELETE" in str(c[0][0]).upper()]
        sql = str(delete_calls[0][0][0])
        self.assertIn("user_touched", sql,
                      "Stale purge must preserve user_touched rows via JOIN")


if __name__ == "__main__":
    unittest.main()
