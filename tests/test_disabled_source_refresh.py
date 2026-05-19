"""
Tests that disabled event sources are not fetched during refresh.

Covers:
  - refresh_all_stale() skips sources with enabled=FALSE in event_sources
  - refresh_all() skips disabled sources
  - any_source_stale() ignores disabled sources
  - Enabled sources still fetch normally when stale

Run with:  python3 -m pytest tests/ -v
"""
import sys
import os
import unittest
import unittest.mock
import datetime

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "api"))
import events as _ev


def _make_conn(enabled_keys, stale_keys=None):
    """
    Build a mock DB connection for refresh/stale tests.

    enabled_keys : set of source_key strings returned by event_sources WHERE enabled=TRUE
    stale_keys   : set of keys that have no last_success_at (treated as stale).
                   Defaults to all enabled_keys.
    """
    if stale_keys is None:
        stale_keys = set(enabled_keys)

    conn = unittest.mock.MagicMock()

    def _cursor_factory(dictionary=False):
        cur = unittest.mock.MagicMock()

        def _execute(sql, params=None):
            sql_u = sql.upper()

            # get_enabled_source_keys query
            if "ENABLED = TRUE" in sql_u or "ENABLED=TRUE" in sql_u or (
                    "ENABLED" in sql_u and "SELECT SOURCE_KEY" in sql_u):
                cur._rows = [(k,) for k in enabled_keys]

            # _is_stale query — keyed on source_key param
            elif "LAST_SUCCESS_AT" in sql_u and params:
                key = params[0]
                if key in stale_keys:
                    cur._rows = [{"last_success_at": None}] if dictionary else [{"last_success_at": None}]
                    cur._dict_row = {"last_success_at": None}
                else:
                    recent = datetime.datetime.utcnow()
                    cur._dict_row = {"last_success_at": recent}
                    cur._rows = [{"last_success_at": recent}]

            # _ensure_source INSERT / _mark_success / _mark_error UPDATEs — ignore
            else:
                cur._rows = []
                cur._dict_row = None

        cur.execute.side_effect = _execute

        def _fetchone():
            if hasattr(cur, "_dict_row"):
                return cur._dict_row
            rows = getattr(cur, "_rows", [])
            return rows[0] if rows else None

        def _fetchall():
            rows = getattr(cur, "_rows", [])
            if dictionary and rows and isinstance(rows[0], dict):
                return rows
            return [(k,) for k in enabled_keys] if rows else []

        cur.fetchone.side_effect = _fetchone
        cur.fetchall.side_effect = _fetchall
        return cur

    conn.cursor.side_effect = _cursor_factory
    return conn


def _register_test_adapters(*keys):
    """Register lightweight mock adapters and return their fetch mocks."""
    fetch_mocks = {}
    for key in keys:
        adapter = unittest.mock.MagicMock()
        adapter.source_key = key
        adapter.display_name = key.title()
        fetch_mock = unittest.mock.MagicMock(return_value=[])
        adapter.fetch.side_effect = fetch_mock
        _ev._ADAPTERS[key] = adapter
        fetch_mocks[key] = adapter.fetch
    return fetch_mocks


def _cleanup(*keys):
    for key in keys:
        _ev._ADAPTERS.pop(key, None)


class TestDisabledSourceNotFetched(unittest.TestCase):
    """refresh_all_stale and refresh_all skip sources with enabled=FALSE."""

    def setUp(self):
        self._keys = ("src_enabled", "src_disabled")
        self._fetches = _register_test_adapters(*self._keys)

    def tearDown(self):
        _cleanup(*self._keys)

    def test_refresh_all_stale_skips_disabled(self):
        # Only src_enabled is in event_sources with enabled=TRUE
        conn = _make_conn(enabled_keys={"src_enabled"},
                          stale_keys={"src_enabled", "src_disabled"})
        _ev.refresh_all_stale(conn)
        self._fetches["src_enabled"].assert_called_once()
        self._fetches["src_disabled"].assert_not_called()

    def test_refresh_all_skips_disabled(self):
        conn = _make_conn(enabled_keys={"src_enabled"})
        _ev.refresh_all(conn)
        self._fetches["src_enabled"].assert_called_once()
        self._fetches["src_disabled"].assert_not_called()

    def test_both_enabled_both_fetched(self):
        conn = _make_conn(enabled_keys={"src_enabled", "src_disabled"},
                          stale_keys={"src_enabled", "src_disabled"})
        _ev.refresh_all_stale(conn)
        self._fetches["src_enabled"].assert_called_once()
        self._fetches["src_disabled"].assert_called_once()

    def test_refresh_all_stale_non_stale_enabled_not_fetched(self):
        # src_enabled is enabled but not stale — should be skipped
        conn = _make_conn(enabled_keys={"src_enabled"}, stale_keys=set())
        _ev.refresh_all_stale(conn)
        self._fetches["src_enabled"].assert_not_called()
        self._fetches["src_disabled"].assert_not_called()


class TestAnySourceStaleRespectsEnabled(unittest.TestCase):
    """any_source_stale() only considers enabled sources."""

    def setUp(self):
        self._keys = ("stale_enabled", "stale_disabled")
        _register_test_adapters(*self._keys)

    def tearDown(self):
        _cleanup(*self._keys)

    def test_disabled_stale_source_does_not_trigger_refresh(self):
        # Only the disabled source is stale — any_source_stale should return False
        conn = _make_conn(enabled_keys=set(), stale_keys={"stale_disabled"})
        self.assertFalse(_ev.any_source_stale(conn))

    def test_enabled_stale_source_triggers_refresh(self):
        conn = _make_conn(enabled_keys={"stale_enabled"}, stale_keys={"stale_enabled"})
        self.assertTrue(_ev.any_source_stale(conn))

    def test_enabled_not_stale_returns_false(self):
        conn = _make_conn(enabled_keys={"stale_enabled"}, stale_keys=set())
        self.assertFalse(_ev.any_source_stale(conn))


if __name__ == "__main__":
    unittest.main()
