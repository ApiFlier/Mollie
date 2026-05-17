"""
Tests for PittsburghParks and PittsburghGlassCenter adapters.

PittsburghParks: TribeEventsAdapter subclass with a longitude-sign fix for
  venues with positive (incorrectly entered) longitude values.

PittsburghGlassCenter: TribeEventsAdapter subclass with venue fallback for
  events that have no venue data in the API response.

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
if not hasattr(_adapters, "__path__"):
    _adapters.__path__ = []

class _BaseAdapter:
    source_key   = None
    display_name = None
    api_base     = None
    def fetch(self, coverage_days=30):
        return []

_adapters_base.BaseAdapter = _BaseAdapter

_ev = _stub_module("events")
_ev.make_fingerprint = lambda title, date_str, venue: f"fp-{title}-{date_str}"

_stub_module("requests")


# ── Load modules ──────────────────────────────────────────────────────────────

def _load(rel_path, module_name):
    path = os.path.join(os.path.dirname(__file__), "..", "api", rel_path)
    spec = importlib.util.spec_from_file_location(module_name, path)
    mod  = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod

_tribe_mod = _load("adapters/tribe_events.py", "tribe_events")
sys.modules["tribe_events"]          = _tribe_mod
sys.modules["adapters.tribe_events"] = _tribe_mod

_parks_mod = _load("adapters/pittsburgh_parks.py", "pittsburgh_parks")
_glass_mod = _load("adapters/pittsburgh_glass_center.py", "pittsburgh_glass_center")

PittsburghParks       = _parks_mod.PittsburghParks
PittsburghGlassCenter = _glass_mod.PittsburghGlassCenter
TribeEventsAdapter    = _tribe_mod.TribeEventsAdapter


# ── Helpers ───────────────────────────────────────────────────────────────────

def _make_ev(ev_id=1, **overrides):
    base = {
        "id":           ev_id,
        "title":        "Test Event",
        "excerpt":      "<p>Short description.</p>",
        "start_date":   "2026-06-10 10:00:00",
        "end_date":     "2026-06-10 12:00:00",
        "url":          "https://example.org/event/test/",
        "website":      None,
        "cost":         "",
        "cost_details": {"values": []},
        "image":        {"url": "https://example.org/img.jpg"},
        "categories":   [{"name": "Outdoor"}],
        "venue":        {
            "venue":        "Test Venue",
            "address":      "100 Park Ave",
            "city":         "Pittsburgh",
            "stateprovince": "PA",
            "zip":          "15213",
            "geo_lat":      40.44,
            "geo_lng":      -79.95,
        },
        "is_virtual":   False,
    }
    base.update(overrides)
    return base

def _page(events, total_pages=1):
    return {"events": events, "total": len(events), "total_pages": total_pages}

def _mock_requests(pages):
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
# PittsburghParks — metadata
# ══════════════════════════════════════════════════════════════════════════════

class TestPittsburghParksMetadata(unittest.TestCase):
    def setUp(self):
        self.adapter = PittsburghParks()

    def test_source_key(self):
        self.assertEqual(self.adapter.source_key, "pittsburgh_parks")

    def test_display_name(self):
        self.assertEqual(self.adapter.display_name, "Pittsburgh Parks Conservancy")

    def test_api_base(self):
        self.assertEqual(self.adapter.api_base, "https://www.pittsburghparks.org")

    def test_is_tribe_adapter(self):
        self.assertIsInstance(self.adapter, TribeEventsAdapter)

    def test_endpoint_url(self):
        mock = _mock_requests([_page([])])
        with unittest.mock.patch.object(_tribe_mod, "requests", mock):
            self.adapter.fetch()
        url = mock.get.call_args[0][0]
        self.assertEqual(url, "https://www.pittsburghparks.org/wp-json/tribe/events/v1/events")


# ══════════════════════════════════════════════════════════════════════════════
# PittsburghParks — longitude-sign fix
# ══════════════════════════════════════════════════════════════════════════════

class TestPittsburghParksGeoFix(unittest.TestCase):
    def setUp(self):
        self.adapter = PittsburghParks()

    def test_correct_negative_lng_unchanged(self):
        ev = _make_ev(venue={
            "venue": "Frick Park", "address": "101 S. Braddock Ave",
            "city": "Pittsburgh", "stateprovince": "PA", "zip": "15208",
            "geo_lat": 40.44, "geo_lng": -79.91,
        })
        mock = _mock_requests([_page([ev])])
        with unittest.mock.patch.object(_tribe_mod, "requests", mock):
            results = self.adapter.fetch()
        self.assertEqual(results[0]["longitude"], -79.91)

    def test_positive_lng_negated(self):
        ev = _make_ev(venue={
            "venue": "Hays Woods", "address": "Agnew Rd",
            "city": "Baldwin", "stateprovince": "PA", "zip": "15207",
            "geo_lat": 40.39853565734576, "geo_lng": 79.9628706085842,
        })
        mock = _mock_requests([_page([ev])])
        with unittest.mock.patch.object(_tribe_mod, "requests", mock):
            results = self.adapter.fetch()
        self.assertAlmostEqual(results[0]["longitude"], -79.9628706085842, places=4)

    def test_positive_lng_negated_float_value(self):
        ev = _make_ev(venue={
            "venue": "Test Park", "address": "1 Park Way",
            "city": "Pittsburgh", "stateprovince": "PA", "zip": "15222",
            "geo_lat": 40.44, "geo_lng": 79.95,
        })
        mock = _mock_requests([_page([ev])])
        with unittest.mock.patch.object(_tribe_mod, "requests", mock):
            results = self.adapter.fetch()
        self.assertLess(results[0]["longitude"], 0)

    def test_no_geo_event_not_crashed(self):
        ev = _make_ev(venue={
            "venue": "City Park", "address": "1 Main St",
            "city": "Pittsburgh", "stateprovince": "PA", "zip": "15222",
            "geo_lat": None, "geo_lng": None,
        })
        mock = _mock_requests([_page([ev])])
        with unittest.mock.patch.object(_tribe_mod, "requests", mock):
            results = self.adapter.fetch()
        self.assertEqual(len(results), 1)
        self.assertIsNone(results[0]["latitude"])
        self.assertIsNone(results[0]["longitude"])

    def test_virtual_events_excluded(self):
        real    = _make_ev(ev_id=1)
        virtual = _make_ev(ev_id=2, is_virtual=True, title="Virtual Walk")
        mock = _mock_requests([_page([real, virtual])])
        with unittest.mock.patch.object(_tribe_mod, "requests", mock):
            results = self.adapter.fetch()
        self.assertEqual(len(results), 1)
        self.assertNotEqual(results[0]["title"], "Virtual Walk")

    def test_source_key_propagated(self):
        mock = _mock_requests([_page([_make_ev()])])
        with unittest.mock.patch.object(_tribe_mod, "requests", mock):
            results = self.adapter.fetch()
        self.assertEqual(results[0]["source_key"], "pittsburgh_parks")

    def test_images_preserved(self):
        ev = _make_ev(image={"url": "https://pittsburghparks.org/img/yoga.jpg"})
        mock = _mock_requests([_page([ev])])
        with unittest.mock.patch.object(_tribe_mod, "requests", mock):
            results = self.adapter.fetch()
        self.assertEqual(results[0]["image_url"], "https://pittsburghparks.org/img/yoga.jpg")

    def test_coverage_days_default(self):
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

    def test_multiple_events_geo_fix_applied_to_all(self):
        evs = [
            _make_ev(ev_id=1, venue={"venue": "Park A", "address": "1 A",
                "city": "Pittsburgh", "stateprovince": "PA", "zip": "15222",
                "geo_lat": 40.44, "geo_lng": 79.95}),
            _make_ev(ev_id=2, venue={"venue": "Park B", "address": "2 B",
                "city": "Pittsburgh", "stateprovince": "PA", "zip": "15222",
                "geo_lat": 40.43, "geo_lng": 79.91}),
        ]
        mock = _mock_requests([_page(evs)])
        with unittest.mock.patch.object(_tribe_mod, "requests", mock):
            results = self.adapter.fetch()
        self.assertLess(results[0]["longitude"], 0)
        self.assertLess(results[1]["longitude"], 0)

    def test_raw_source_json_valid(self):
        mock = _mock_requests([_page([_make_ev()])])
        with unittest.mock.patch.object(_tribe_mod, "requests", mock):
            results = self.adapter.fetch()
        raw = json.loads(results[0]["raw_source_json"])
        self.assertIsInstance(raw, dict)


# ══════════════════════════════════════════════════════════════════════════════
# PittsburghGlassCenter — metadata
# ══════════════════════════════════════════════════════════════════════════════

class TestPittsburghGlassCenterMetadata(unittest.TestCase):
    def setUp(self):
        self.adapter = PittsburghGlassCenter()

    def test_source_key(self):
        self.assertEqual(self.adapter.source_key, "pittsburgh_glass_center")

    def test_display_name(self):
        self.assertEqual(self.adapter.display_name, "Pittsburgh Glass Center")

    def test_api_base(self):
        self.assertEqual(self.adapter.api_base, "https://www.pittsburghglasscenter.org")

    def test_is_tribe_adapter(self):
        self.assertIsInstance(self.adapter, TribeEventsAdapter)

    def test_endpoint_url(self):
        mock = _mock_requests([_page([])])
        with unittest.mock.patch.object(_tribe_mod, "requests", mock):
            self.adapter.fetch()
        url = mock.get.call_args[0][0]
        self.assertEqual(url, "https://www.pittsburghglasscenter.org/wp-json/tribe/events/v1/events")


# ══════════════════════════════════════════════════════════════════════════════
# PittsburghGlassCenter — venue fallback
# ══════════════════════════════════════════════════════════════════════════════

class TestPittsburghGlassCenterFallback(unittest.TestCase):
    def setUp(self):
        self.adapter = PittsburghGlassCenter()

    def _ev_no_venue(self, **overrides):
        ev = _make_ev(**overrides)
        ev["venue"] = {}
        return ev

    def test_fallback_venue_name_applied(self):
        mock = _mock_requests([_page([self._ev_no_venue()])])
        with unittest.mock.patch.object(_tribe_mod, "requests", mock):
            results = self.adapter.fetch()
        self.assertEqual(results[0]["venue_name"], "Pittsburgh Glass Center")

    def test_fallback_address_applied(self):
        mock = _mock_requests([_page([self._ev_no_venue()])])
        with unittest.mock.patch.object(_tribe_mod, "requests", mock):
            results = self.adapter.fetch()
        self.assertEqual(results[0]["address"], "5472 Penn Ave")

    def test_fallback_city_applied(self):
        mock = _mock_requests([_page([self._ev_no_venue()])])
        with unittest.mock.patch.object(_tribe_mod, "requests", mock):
            results = self.adapter.fetch()
        self.assertEqual(results[0]["city"], "Pittsburgh")

    def test_fallback_state_applied(self):
        mock = _mock_requests([_page([self._ev_no_venue()])])
        with unittest.mock.patch.object(_tribe_mod, "requests", mock):
            results = self.adapter.fetch()
        self.assertEqual(results[0]["state"], "PA")

    def test_fallback_zip_applied(self):
        mock = _mock_requests([_page([self._ev_no_venue()])])
        with unittest.mock.patch.object(_tribe_mod, "requests", mock):
            results = self.adapter.fetch()
        self.assertEqual(results[0]["postal_code"], "15206")

    def test_fallback_lat_applied(self):
        mock = _mock_requests([_page([self._ev_no_venue()])])
        with unittest.mock.patch.object(_tribe_mod, "requests", mock):
            results = self.adapter.fetch()
        self.assertAlmostEqual(results[0]["latitude"], 40.4628, places=2)

    def test_fallback_lng_applied(self):
        mock = _mock_requests([_page([self._ev_no_venue()])])
        with unittest.mock.patch.object(_tribe_mod, "requests", mock):
            results = self.adapter.fetch()
        self.assertAlmostEqual(results[0]["longitude"], -79.9270, places=2)

    def test_existing_venue_not_overwritten(self):
        ev = _make_ev(venue={
            "venue": "Offsite Venue", "address": "100 Somewhere St",
            "city": "Pittsburgh", "stateprovince": "PA", "zip": "15201",
            "geo_lat": 40.45, "geo_lng": -79.96,
        })
        mock = _mock_requests([_page([ev])])
        with unittest.mock.patch.object(_tribe_mod, "requests", mock):
            results = self.adapter.fetch()
        self.assertEqual(results[0]["venue_name"], "Offsite Venue")
        self.assertEqual(results[0]["address"], "100 Somewhere St")
        self.assertAlmostEqual(results[0]["latitude"], 40.45, places=2)
        self.assertAlmostEqual(results[0]["longitude"], -79.96, places=2)

    def test_virtual_events_excluded(self):
        real    = self._ev_no_venue(ev_id=1)
        virtual = self._ev_no_venue(ev_id=2, is_virtual=True, title="Virtual Demo")
        mock = _mock_requests([_page([real, virtual])])
        with unittest.mock.patch.object(_tribe_mod, "requests", mock):
            results = self.adapter.fetch()
        self.assertEqual(len(results), 1)
        self.assertNotEqual(results[0]["title"], "Virtual Demo")

    def test_source_key_propagated(self):
        mock = _mock_requests([_page([self._ev_no_venue()])])
        with unittest.mock.patch.object(_tribe_mod, "requests", mock):
            results = self.adapter.fetch()
        self.assertEqual(results[0]["source_key"], "pittsburgh_glass_center")

    def test_image_preserved(self):
        ev = self._ev_no_venue()
        ev["image"] = {"url": "https://pgc.org/walk-in.jpg"}
        mock = _mock_requests([_page([ev])])
        with unittest.mock.patch.object(_tribe_mod, "requests", mock):
            results = self.adapter.fetch()
        self.assertEqual(results[0]["image_url"], "https://pgc.org/walk-in.jpg")

    def test_no_image_returns_none(self):
        ev = self._ev_no_venue()
        ev["image"] = None
        mock = _mock_requests([_page([ev])])
        with unittest.mock.patch.object(_tribe_mod, "requests", mock):
            results = self.adapter.fetch()
        self.assertIsNone(results[0]["image_url"])

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

    def test_raw_source_json_valid(self):
        mock = _mock_requests([_page([self._ev_no_venue()])])
        with unittest.mock.patch.object(_tribe_mod, "requests", mock):
            results = self.adapter.fetch()
        raw = json.loads(results[0]["raw_source_json"])
        self.assertIsInstance(raw, dict)

    def test_fallback_lat_is_western_pa(self):
        """Sanity: fallback lat/lng are in the Pittsburgh area."""
        fallback_lat = _glass_mod._FALLBACK["latitude"]
        fallback_lng = _glass_mod._FALLBACK["longitude"]
        self.assertGreater(fallback_lat, 40.0)
        self.assertLess(fallback_lat, 41.0)
        self.assertLess(fallback_lng, -79.5)
        self.assertGreater(fallback_lng, -80.5)


if __name__ == "__main__":
    unittest.main()
