"""
Tests for CarnegieLibrary and WqedCultural adapters.

Both are thin subclasses of TribeEventsAdapter, so we verify:
  - correct source_key, display_name, api_base metadata
  - correct Tribe endpoint is constructed from api_base
  - normalization (via shared base) works on real-shaped payloads
  - virtual events are excluded
  - source_key propagates to normalized events

Run with:  python3 -m pytest tests/ -v
"""
import sys
import os
import types
import importlib.util
import unittest
import unittest.mock
import json
from datetime import datetime, timedelta


# ── Stub heavy deps before loading adapter modules ────────────────────────────

def _stub_module(name):
    m = types.ModuleType(name)
    sys.modules.setdefault(name, m)
    return sys.modules[name]

_adapters      = _stub_module("adapters")
_adapters_base = _stub_module("adapters.base")
if not hasattr(_adapters, '__path__'):
    _adapters.__path__ = []

class _BaseAdapter:
    source_key   = None
    display_name = None
    api_base     = None
    def fetch(self, coverage_days=30):
        return []

_adapters_base.BaseAdapter = _BaseAdapter

_ev = _stub_module("events")
_ev.make_fingerprint = lambda src, eid, dt, title=None, venue=None: f"fp-{src}-{eid}-{dt}"
_ev.make_series_key = lambda src, title: f"sk-{src}-{title}"

_stub_module("requests")


# ── Load modules ──────────────────────────────────────────────────────────────

def _load(rel_path, module_name):
    path = os.path.join(os.path.dirname(__file__), "..", "api", rel_path)
    spec = importlib.util.spec_from_file_location(module_name, path)
    mod  = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod

_tribe_mod = _load("adapters/tribe_events.py", "tribe_events")
sys.modules["tribe_events"] = _tribe_mod
sys.modules["adapters.tribe_events"] = _tribe_mod

_clp_mod  = _load("adapters/carnegie_library.py", "carnegie_library")
_wqed_mod = _load("adapters/wqed_cultural.py", "wqed_cultural")

CarnegieLibrary    = _clp_mod.CarnegieLibrary
WqedCultural       = _wqed_mod.WqedCultural
TribeEventsAdapter = _tribe_mod.TribeEventsAdapter


# ── Helpers ───────────────────────────────────────────────────────────────────

def _make_ev(source_key="test", **overrides):
    base = {
        "id": 9001,
        "title": "Sample Event",
        "excerpt": "<p>A short excerpt.</p>",
        "start_date": "2026-06-15 10:00:00",
        "end_date":   "2026-06-15 12:00:00",
        "url":        "https://example.org/event/sample/",
        "website":    None,
        "cost":       "Free",
        "cost_details": {"values": []},
        "image":      {"url": "https://example.org/img.jpg"},
        "categories": [{"name": "Community"}],
        "venue": {
            "venue": "Test Branch",
            "address": "100 Elm St",
            "city": "Pittsburgh",
            "stateprovince": "PA",
            "zip": "15213",
            "geo_lat": 40.44,
            "geo_lng": -79.99,
        },
        "is_virtual": False,
    }
    base.update(overrides)
    return base

def _page(events, total_pages=1):
    return {"events": events, "total": len(events), "total_pages": total_pages}

def _mock_requests(pages):
    """Return a mock requests module serving pages in sequence."""
    idx = [0]
    def _get(url, **kwargs):
        i = idx[0]; idx[0] += 1
        m = unittest.mock.MagicMock()
        m.raise_for_status.return_value = None
        m.json.return_value = pages[i] if i < len(pages) else _page([])
        return m
    mock_req = unittest.mock.MagicMock()
    mock_req.get.side_effect = _get
    return mock_req


# ══════════════════════════════════════════════════════════════════════════════
# CarnegieLibrary metadata
# ══════════════════════════════════════════════════════════════════════════════

class TestCarnegieLibraryMetadata(unittest.TestCase):
    def setUp(self):
        self.adapter = CarnegieLibrary()

    def test_source_key(self):
        self.assertEqual(self.adapter.source_key, "carnegie_library")

    def test_display_name(self):
        self.assertEqual(self.adapter.display_name, "Carnegie Library of Pittsburgh")

    def test_api_base(self):
        self.assertEqual(self.adapter.api_base, "https://www.carnegielibrary.org")

    def test_is_tribe_adapter(self):
        self.assertIsInstance(self.adapter, TribeEventsAdapter)

    def test_endpoint_constructed_correctly(self):
        mock = _mock_requests([_page([])])
        with unittest.mock.patch.object(_tribe_mod, "requests", mock):
            self.adapter.fetch()
        url = mock.get.call_args[0][0]
        self.assertEqual(url, "https://www.carnegielibrary.org/wp-json/tribe/events/v1/events")


# ══════════════════════════════════════════════════════════════════════════════
# CarnegieLibrary fetch behavior
# ══════════════════════════════════════════════════════════════════════════════

class TestCarnegieLibraryFetch(unittest.TestCase):
    def setUp(self):
        self.adapter = CarnegieLibrary()

    def test_fetch_returns_normalized_events(self):
        ev = _make_ev()
        mock = _mock_requests([_page([ev])])
        with unittest.mock.patch.object(_tribe_mod, "requests", mock):
            results = self.adapter.fetch()
        self.assertEqual(len(results), 1)
        self.assertEqual(results[0]["source_key"], "carnegie_library")
        self.assertEqual(results[0]["title"], "Sample Event")
        self.assertEqual(results[0]["admission"], "Free")

    def test_virtual_events_excluded(self):
        real    = _make_ev(id=9001)
        virtual = _make_ev(id=9002, is_virtual=True)
        mock = _mock_requests([_page([real, virtual])])
        with unittest.mock.patch.object(_tribe_mod, "requests", mock):
            results = self.adapter.fetch()
        self.assertEqual(len(results), 1)
        self.assertEqual(results[0]["title"], "Sample Event")

    def test_venue_geo_propagated(self):
        ev = _make_ev()
        mock = _mock_requests([_page([ev])])
        with unittest.mock.patch.object(_tribe_mod, "requests", mock):
            results = self.adapter.fetch()
        self.assertEqual(results[0]["latitude"], 40.44)
        self.assertEqual(results[0]["longitude"], -79.99)

    def test_city_title_cased(self):
        ev = _make_ev(venue=dict(
            venue="CLP - Main", address="4400 Forbes Ave",
            city="pittsburgh", stateprovince="PA", zip="15213",
            geo_lat=40.44, geo_lng=-79.95
        ))
        mock = _mock_requests([_page([ev])])
        with unittest.mock.patch.object(_tribe_mod, "requests", mock):
            results = self.adapter.fetch()
        self.assertEqual(results[0]["city"], "Pittsburgh")

    def test_html_entities_in_venue_name_decoded(self):
        ev = _make_ev(venue=dict(
            venue="CLP &#8211; Squirrel Hill", address="5801 Forbes Ave",
            city="Pittsburgh", stateprovince="PA", zip="15217",
            geo_lat=40.43, geo_lng=-79.92
        ))
        mock = _mock_requests([_page([ev])])
        with unittest.mock.patch.object(_tribe_mod, "requests", mock):
            results = self.adapter.fetch()
        self.assertNotIn("&#8211;", results[0]["venue_name"])
        self.assertIn("–", results[0]["venue_name"])

    def test_coverage_days_30_default(self):
        captured = {}
        def _get(url, params=None, **kwargs):
            captured.update(params or {})
            m = unittest.mock.MagicMock()
            m.raise_for_status.return_value = None
            m.json.return_value = _page([])
            return m
        mock = unittest.mock.MagicMock()
        mock.get.side_effect = _get
        with unittest.mock.patch.object(_tribe_mod, "requests", mock):
            self.adapter.fetch(coverage_days=30)
        expected_end = (datetime.utcnow() + timedelta(days=30)).strftime("%Y-%m-%d")
        self.assertIn(expected_end, captured.get("end_date", ""))

    def test_coverage_days_clamps_low(self):
        captured = {}
        def _get(url, params=None, **kwargs):
            captured.update(params or {})
            m = unittest.mock.MagicMock()
            m.raise_for_status.return_value = None
            m.json.return_value = _page([])
            return m
        mock = unittest.mock.MagicMock()
        mock.get.side_effect = _get
        with unittest.mock.patch.object(_tribe_mod, "requests", mock):
            self.adapter.fetch(coverage_days=2)
        expected = (datetime.utcnow() + timedelta(days=7)).strftime("%Y-%m-%d")
        self.assertIn(expected, captured.get("end_date", ""))

    def test_no_geo_events_still_included(self):
        ev = _make_ev(venue=dict(
            venue="CLP - Branch", address="1 Library St",
            city="Pittsburgh", stateprovince="PA", zip="15201",
            geo_lat=None, geo_lng=None
        ))
        mock = _mock_requests([_page([ev])])
        with unittest.mock.patch.object(_tribe_mod, "requests", mock):
            results = self.adapter.fetch()
        self.assertEqual(len(results), 1)
        self.assertIsNone(results[0]["latitude"])
        self.assertIsNone(results[0]["longitude"])

    def test_raw_source_json_excludes_description(self):
        ev = _make_ev()
        ev["description"] = "<p>Long HTML description</p>"
        mock = _mock_requests([_page([ev])])
        with unittest.mock.patch.object(_tribe_mod, "requests", mock):
            results = self.adapter.fetch()
        raw = json.loads(results[0]["raw_source_json"])
        self.assertNotIn("description", raw)

    def test_deduplication_by_id(self):
        ev1 = _make_ev(id=100)
        ev2 = _make_ev(id=100)  # same id, second page
        pages = [
            _page([ev1], total_pages=2),
            _page([ev2], total_pages=2),
        ]
        mock = _mock_requests(pages)
        with unittest.mock.patch.object(_tribe_mod, "requests", mock):
            results = self.adapter.fetch()
        self.assertEqual(len(results), 1)


# ══════════════════════════════════════════════════════════════════════════════
# WqedCultural metadata
# ══════════════════════════════════════════════════════════════════════════════

class TestWqedCulturalMetadata(unittest.TestCase):
    def setUp(self):
        self.adapter = WqedCultural()

    def test_source_key(self):
        self.assertEqual(self.adapter.source_key, "wqed_cultural")

    def test_display_name(self):
        self.assertEqual(self.adapter.display_name, "WQED Cultural Calendar")

    def test_api_base(self):
        self.assertEqual(self.adapter.api_base, "https://www.wqed.org")

    def test_is_tribe_adapter(self):
        self.assertIsInstance(self.adapter, TribeEventsAdapter)

    def test_endpoint_constructed_correctly(self):
        mock = _mock_requests([_page([])])
        with unittest.mock.patch.object(_tribe_mod, "requests", mock):
            self.adapter.fetch()
        url = mock.get.call_args[0][0]
        self.assertEqual(url, "https://www.wqed.org/wp-json/tribe/events/v1/events")


# ══════════════════════════════════════════════════════════════════════════════
# WqedCultural fetch behavior
# ══════════════════════════════════════════════════════════════════════════════

class TestWqedCulturalFetch(unittest.TestCase):
    def setUp(self):
        self.adapter = WqedCultural()

    def test_fetch_returns_normalized_events(self):
        ev = _make_ev()
        mock = _mock_requests([_page([ev])])
        with unittest.mock.patch.object(_tribe_mod, "requests", mock):
            results = self.adapter.fetch()
        self.assertEqual(len(results), 1)
        self.assertEqual(results[0]["source_key"], "wqed_cultural")

    def test_virtual_events_excluded(self):
        ev1 = _make_ev(id=9001)
        ev2 = _make_ev(id=9002, is_virtual=True, title="Virtual Talk")
        mock = _mock_requests([_page([ev1, ev2])])
        with unittest.mock.patch.object(_tribe_mod, "requests", mock):
            results = self.adapter.fetch()
        self.assertEqual(len(results), 1)
        self.assertNotEqual(results[0]["title"], "Virtual Talk")

    def test_no_geo_event_included(self):
        ev = _make_ev(venue=dict(
            venue="Kresge Theatre", address="100 Forbes Ave",
            city="Pittsburgh", stateprovince="PA", zip="15213",
            geo_lat=None, geo_lng=None
        ))
        mock = _mock_requests([_page([ev])])
        with unittest.mock.patch.object(_tribe_mod, "requests", mock):
            results = self.adapter.fetch()
        self.assertEqual(len(results), 1)
        self.assertIsNone(results[0]["latitude"])
        self.assertIsNone(results[0]["longitude"])

    def test_paid_cost_parsed(self):
        ev = _make_ev(cost="$15", cost_details={"values": [15]})
        mock = _mock_requests([_page([ev])])
        with unittest.mock.patch.object(_tribe_mod, "requests", mock):
            results = self.adapter.fetch()
        self.assertEqual(results[0]["admission"], "$15")

    def test_free_cost_parsed(self):
        ev = _make_ev(cost="Free", cost_details={"values": []})
        mock = _mock_requests([_page([ev])])
        with unittest.mock.patch.object(_tribe_mod, "requests", mock):
            results = self.adapter.fetch()
        self.assertEqual(results[0]["admission"], "Free")

    def test_category_extracted(self):
        ev = _make_ev(categories=[{"name": "Cultural Calendar Community Event"}])
        mock = _mock_requests([_page([ev])])
        with unittest.mock.patch.object(_tribe_mod, "requests", mock):
            results = self.adapter.fetch()
        self.assertEqual(results[0]["category"], "Cultural Calendar Community Event")

    def test_source_url_set(self):
        ev = _make_ev(url="https://www.wqed.org/event/some-event/")
        mock = _mock_requests([_page([ev])])
        with unittest.mock.patch.object(_tribe_mod, "requests", mock):
            results = self.adapter.fetch()
        self.assertEqual(results[0]["source_url"], "https://www.wqed.org/event/some-event/")

    def test_image_url_extracted(self):
        ev = _make_ev(image={"url": "https://www.wqed.org/wp-content/img.jpg"})
        mock = _mock_requests([_page([ev])])
        with unittest.mock.patch.object(_tribe_mod, "requests", mock):
            results = self.adapter.fetch()
        self.assertEqual(results[0]["image_url"], "https://www.wqed.org/wp-content/img.jpg")

    def test_coverage_days_45(self):
        captured = {}
        def _get(url, params=None, **kwargs):
            captured.update(params or {})
            m = unittest.mock.MagicMock()
            m.raise_for_status.return_value = None
            m.json.return_value = _page([])
            return m
        mock = unittest.mock.MagicMock()
        mock.get.side_effect = _get
        with unittest.mock.patch.object(_tribe_mod, "requests", mock):
            self.adapter.fetch(coverage_days=45)
        expected = (datetime.utcnow() + timedelta(days=45)).strftime("%Y-%m-%d")
        self.assertIn(expected, captured.get("end_date", ""))

    def test_result_has_required_keys(self):
        ev = _make_ev()
        mock = _mock_requests([_page([ev])])
        with unittest.mock.patch.object(_tribe_mod, "requests", mock):
            results = self.adapter.fetch()
        required = {
            "source_key", "source_event_id", "source_url", "title",
            "start_datetime", "end_datetime", "date_label",
            "venue_name", "address", "city", "state", "postal_code",
            "latitude", "longitude", "category", "image_url", "admission",
            "normalized_fingerprint", "raw_source_json",
        }
        for key in required:
            self.assertIn(key, results[0], f"Missing key: {key}")

    def test_no_image_returns_none(self):
        ev = _make_ev(image=None)
        mock = _mock_requests([_page([ev])])
        with unittest.mock.patch.object(_tribe_mod, "requests", mock):
            results = self.adapter.fetch()
        self.assertIsNone(results[0]["image_url"])


if __name__ == "__main__":
    unittest.main()
