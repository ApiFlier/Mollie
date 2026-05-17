"""
Tests for the shared TribeEventsAdapter and its helper functions.
Covers: normalization, price parsing, virtual-event skipping, pagination,
        coverage_days behavior, and deduplication.

Run with:  python3 -m pytest tests/ -v
"""
import sys
import os
import types
import importlib.util
import unittest
import unittest.mock
import json
import datetime

# ── Stub heavy deps before loading adapter modules ────────────────────────────

def _stub_module(name):
    m = types.ModuleType(name)
    sys.modules[name] = m
    return m

_adapters      = _stub_module("adapters")
_adapters_base = _stub_module("adapters.base")
_adapters.__path__ = []

class _BaseAdapter:
    source_key   = None
    display_name = None
    api_base     = None
    def fetch(self, coverage_days=60):
        return []

_adapters_base.BaseAdapter = _BaseAdapter

_ev = _stub_module("events")
_ev.make_fingerprint = lambda src, eid, dt, title=None, venue=None: f"fp-{src}-{eid}-{dt}"
_ev.make_series_key = lambda src, title: f"sk-{src}-{title}"

_stub_module("requests")

# ── Load tribe_events module directly ─────────────────────────────────────────

_tribe_path = os.path.join(
    os.path.dirname(__file__), "..", "api", "adapters", "tribe_events.py"
)
_spec = importlib.util.spec_from_file_location("tribe_events", _tribe_path)
_mod  = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(_mod)

_strip_html        = _mod._strip_html
_parse_tribe_cost  = _mod._parse_tribe_cost
_normalize         = _mod._normalize
TribeEventsAdapter = _mod.TribeEventsAdapter


# ── Fixtures ──────────────────────────────────────────────────────────────────

def _make_ev(**overrides):
    """Build a minimal Tribe Events API event dict."""
    base = {
        "id": 1001,
        "title": "Test Event",
        "excerpt": "<p>A short description.</p>",
        "start_date": "2026-06-01 10:00:00",
        "end_date":   "2026-06-01 12:00:00",
        "url":        "https://example.org/event/test-event/",
        "website":    None,
        "cost":       "",
        "cost_details": {"currency_symbol": "$", "currency_code": "USD",
                         "currency_position": "prefix", "values": []},
        "image":      None,
        "categories": [],
        "venue":      {
            "venue": "Test Venue", "address": "123 Main St",
            "city": "pittsburgh", "stateprovince": "PA", "zip": "15213",
            "geo_lat": None, "geo_lng": None,
        },
        "is_virtual": False,
        "all_day":    False,
    }
    base.update(overrides)
    return base


def _page(events, total=None, total_pages=None):
    """Build a fake Tribe API page response."""
    n = total if total is not None else len(events)
    p = total_pages if total_pages is not None else 1
    return {"events": events, "total": n, "total_pages": p, "next_rest_url": None}


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


class _ConcreteAdapter(TribeEventsAdapter):
    source_key   = "test_source"
    display_name = "Test Source"
    api_base     = "https://example.org"


# ═══════════════════════════════════════════════════════════════════════════════
# Strip HTML
# ═══════════════════════════════════════════════════════════════════════════════

class TestStripHtml(unittest.TestCase):

    def test_removes_tags(self):
        self.assertEqual(_strip_html("<p>Hello <b>world</b></p>"), "Hello world")

    def test_decodes_entities(self):
        self.assertEqual(_strip_html("Kids &amp; Families"), "Kids & Families")

    def test_collapses_whitespace(self):
        self.assertEqual(_strip_html("  lots   of   space  "), "lots of space")

    def test_none_returns_none(self):
        self.assertIsNone(_strip_html(None))

    def test_empty_returns_none(self):
        self.assertIsNone(_strip_html(""))

    def test_tags_only_returns_none(self):
        self.assertIsNone(_strip_html("<br/><hr/>"))

    def test_unicode_preserved(self):
        self.assertEqual(_strip_html("Café &amp; Résumé"), "Café & Résumé")


# ═══════════════════════════════════════════════════════════════════════════════
# Price parsing
# ═══════════════════════════════════════════════════════════════════════════════

class TestParseTribeCost(unittest.TestCase):

    def _ev(self, cost="", values=None):
        return {"cost": cost, "cost_details": {"values": values or []}}

    def test_empty_cost_no_values_returns_none(self):
        self.assertIsNone(_parse_tribe_cost(self._ev("", [])))

    def test_cost_string_free(self):
        self.assertEqual(_parse_tribe_cost(self._ev("Free")), "Free")

    def test_cost_string_free_case_insensitive(self):
        self.assertEqual(_parse_tribe_cost(self._ev("free")), "Free")

    def test_values_single_price(self):
        self.assertEqual(_parse_tribe_cost(self._ev("", [15])), "$15")

    def test_values_float_price(self):
        self.assertEqual(_parse_tribe_cost(self._ev("", [12.5])), "$12.50")

    def test_values_range(self):
        self.assertEqual(_parse_tribe_cost(self._ev("", [10, 20])), "$10–$20")

    def test_values_zero_is_free(self):
        self.assertEqual(_parse_tribe_cost(self._ev("", [0])), "Free")

    def test_values_same_price_shows_single(self):
        self.assertEqual(_parse_tribe_cost(self._ev("", [15, 15])), "$15")

    def test_cost_string_used_when_no_values(self):
        r = _parse_tribe_cost(self._ev("Members free; $20 general"))
        self.assertEqual(r, "Members free; $20 general")

    def test_free_cost_takes_precedence_over_values(self):
        # "Free" string wins even if values list is non-empty (shouldn't happen, but safe)
        self.assertEqual(_parse_tribe_cost(self._ev("Free", [0])), "Free")


# ═══════════════════════════════════════════════════════════════════════════════
# _normalize
# ═══════════════════════════════════════════════════════════════════════════════

class TestNormalize(unittest.TestCase):

    def test_basic_fields(self):
        ev = _make_ev()
        r  = _normalize(ev, "test_source")
        self.assertIsNotNone(r)
        self.assertEqual(r["source_key"], "test_source")
        self.assertEqual(r["title"], "Test Event")
        self.assertEqual(r["start_datetime"], "2026-06-01 10:00:00")
        self.assertEqual(r["end_datetime"],   "2026-06-01 12:00:00")

    def test_virtual_event_returns_none(self):
        ev = _make_ev(is_virtual=True)
        self.assertIsNone(_normalize(ev, "test_source"))

    def test_city_normalized_to_titlecase(self):
        r = _normalize(_make_ev(), "test_source")
        self.assertEqual(r["city"], "Pittsburgh")

    def test_venue_fields_present(self):
        r = _normalize(_make_ev(), "test_source")
        self.assertEqual(r["venue_name"], "Test Venue")
        self.assertEqual(r["address"],    "123 Main St")
        self.assertEqual(r["state"],      "PA")
        self.assertEqual(r["postal_code"], "15213")

    def test_no_venue_fields_are_none(self):
        ev = _make_ev(venue=None)
        r  = _normalize(ev, "test_source")
        self.assertIsNone(r["venue_name"])
        self.assertIsNone(r["city"])

    def test_source_url_from_url(self):
        r = _normalize(_make_ev(), "test_source")
        self.assertEqual(r["source_url"], "https://example.org/event/test-event/")

    def test_official_url_prefers_website(self):
        ev = _make_ev(website="https://tickets.example.org/buy/123")
        r  = _normalize(ev, "test_source")
        self.assertEqual(r["official_url"], "https://tickets.example.org/buy/123")

    def test_official_url_falls_back_to_url(self):
        ev = _make_ev(website=None)
        r  = _normalize(ev, "test_source")
        self.assertEqual(r["official_url"], "https://example.org/event/test-event/")

    def test_image_url_extracted(self):
        ev = _make_ev(image={"url": "https://example.org/img.jpg"})
        r  = _normalize(ev, "test_source")
        self.assertEqual(r["image_url"], "https://example.org/img.jpg")

    def test_no_image_is_none(self):
        r = _normalize(_make_ev(image=None), "test_source")
        self.assertIsNone(r["image_url"])

    def test_description_stripped_of_html(self):
        ev = _make_ev(excerpt="<p>Hello <b>world</b>.</p>")
        r  = _normalize(ev, "test_source")
        self.assertEqual(r["description_short"], "Hello world.")

    def test_description_truncated_at_280(self):
        ev = _make_ev(excerpt="<p>" + "X" * 400 + "</p>")
        r  = _normalize(ev, "test_source")
        self.assertLessEqual(len(r["description_short"]), 280)
        self.assertTrue(r["description_short"].endswith("…"))

    def test_empty_excerpt_gives_none_description(self):
        r = _normalize(_make_ev(excerpt=""), "test_source")
        self.assertIsNone(r["description_short"])

    def test_category_from_first_category(self):
        ev = _make_ev(categories=[
            {"name": "Kids &amp; Families", "slug": "kids-families"},
            {"name": "Education",           "slug": "education"},
        ])
        r = _normalize(ev, "test_source")
        self.assertEqual(r["category"], "Kids & Families")

    def test_no_category_is_none(self):
        r = _normalize(_make_ev(categories=[]), "test_source")
        self.assertIsNone(r["category"])

    def test_date_label_formatted(self):
        ev = _make_ev(start_date="2026-07-04 10:00:00")
        r  = _normalize(ev, "test_source")
        self.assertEqual(r["date_label"], "Sat Jul 4")

    def test_raw_source_json_is_valid_json(self):
        r   = _normalize(_make_ev(), "test_source")
        raw = json.loads(r["raw_source_json"])
        self.assertIsInstance(raw, dict)

    def test_raw_source_json_excludes_description(self):
        ev  = _make_ev()
        ev["description"] = "<p>Long full description...</p>"
        r   = _normalize(ev, "test_source")
        raw = json.loads(r["raw_source_json"])
        self.assertNotIn("description", raw)

    def test_source_event_id_from_id(self):
        r = _normalize(_make_ev(id=9999), "test_source")
        self.assertEqual(r["source_event_id"], "9999")

    def test_fingerprint_present(self):
        r = _normalize(_make_ev(), "test_source")
        self.assertIn("normalized_fingerprint", r)
        self.assertTrue(r["normalized_fingerprint"])


# ═══════════════════════════════════════════════════════════════════════════════
# Pagination / fetch behavior
# ═══════════════════════════════════════════════════════════════════════════════

class TestTribeAdapterFetch(unittest.TestCase):

    def test_single_page_fetch(self):
        evs  = [_make_ev(id=i) for i in range(10)]
        mock = _mock_requests([_page(evs, total=10, total_pages=1)])
        with unittest.mock.patch.object(_mod, "requests", mock):
            result = _ConcreteAdapter().fetch()
        self.assertEqual(mock.get.call_count, 1)
        self.assertEqual(len(result), 10)

    def test_multi_page_fetch(self):
        page1 = [_make_ev(id=i)       for i in range(100)]
        page2 = [_make_ev(id=i + 100) for i in range(20)]
        pages = [
            _page(page1, total=120, total_pages=2),
            _page(page2, total=120, total_pages=2),
        ]
        mock = _mock_requests(pages)
        with unittest.mock.patch.object(_mod, "requests", mock):
            result = _ConcreteAdapter().fetch()
        self.assertEqual(mock.get.call_count, 2)
        self.assertEqual(len(result), 120)

    def test_stops_at_max_pages_cap(self):
        # Every page returns 100 events and says there are 999 pages
        def _infinite(url, **kwargs):
            page = kwargs.get('params', {}).get('page', 1)
            evs  = [_make_ev(id=page * 100 + i) for i in range(100)]
            m = unittest.mock.MagicMock()
            m.raise_for_status.return_value = None
            m.json.return_value = _page(evs, total=9999, total_pages=999)
            return m
        mock_req = unittest.mock.MagicMock()
        mock_req.get.side_effect = _infinite
        with unittest.mock.patch.object(_mod, "requests", mock_req):
            _ConcreteAdapter().fetch()
        self.assertLessEqual(mock_req.get.call_count, _mod._MAX_PAGES)

    def test_stops_on_empty_batch(self):
        page1 = [_make_ev(id=i) for i in range(50)]
        pages = [
            _page(page1, total=50, total_pages=2),
            _page([],     total=50, total_pages=2),  # empty second page → stop
        ]
        mock = _mock_requests(pages)
        with unittest.mock.patch.object(_mod, "requests", mock):
            result = _ConcreteAdapter().fetch()
        self.assertEqual(len(result), 50)

    def test_deduplication_by_id(self):
        ev1 = _make_ev(id=42)
        ev2 = _make_ev(id=42)  # same id on second page
        pages = [
            _page([ev1] + [_make_ev(id=i) for i in range(99)], total_pages=2),
            _page([ev2], total_pages=2),
        ]
        mock = _mock_requests(pages)
        with unittest.mock.patch.object(_mod, "requests", mock):
            result = _ConcreteAdapter().fetch()
        ids = [e["source_event_id"] for e in result]
        self.assertEqual(ids.count("42"), 1)

    def test_virtual_events_excluded(self):
        evs = [
            _make_ev(id=1, is_virtual=False),
            _make_ev(id=2, is_virtual=True),
            _make_ev(id=3, is_virtual=False),
        ]
        mock = _mock_requests([_page(evs)])
        with unittest.mock.patch.object(_mod, "requests", mock):
            result = _ConcreteAdapter().fetch()
        ids = {e["source_event_id"] for e in result}
        self.assertIn("1", ids)
        self.assertNotIn("2", ids)
        self.assertIn("3", ids)

    def test_fetch_error_on_page_stops_gracefully(self):
        def _fail(url, **kwargs):
            raise Exception("network error")
        mock_req = unittest.mock.MagicMock()
        mock_req.get.side_effect = _fail
        with unittest.mock.patch.object(_mod, "requests", mock_req):
            result = _ConcreteAdapter().fetch()
        self.assertEqual(result, [])

    def test_payload_includes_start_and_end_date(self):
        mock = _mock_requests([_page([])])
        with unittest.mock.patch.object(_mod, "requests", mock):
            _ConcreteAdapter().fetch(coverage_days=60)
        call_params = mock.get.call_args_list[0].kwargs.get('params', {})
        self.assertIn('start_date', call_params)
        self.assertIn('end_date', call_params)

    def test_coverage_days_60_default(self):
        mock = _mock_requests([_page([])])
        with unittest.mock.patch.object(_mod, "requests", mock):
            _ConcreteAdapter().fetch()
        params = mock.get.call_args_list[0].kwargs.get('params', {})
        start = datetime.datetime.strptime(params['start_date'][:10], '%Y-%m-%d').date()
        end   = datetime.datetime.strptime(params['end_date'][:10],   '%Y-%m-%d').date()
        self.assertAlmostEqual((end - start).days, 60, delta=1)

    def test_coverage_days_custom_45(self):
        mock = _mock_requests([_page([])])
        with unittest.mock.patch.object(_mod, "requests", mock):
            _ConcreteAdapter().fetch(coverage_days=45)
        params = mock.get.call_args_list[0].kwargs.get('params', {})
        start = datetime.datetime.strptime(params['start_date'][:10], '%Y-%m-%d').date()
        end   = datetime.datetime.strptime(params['end_date'][:10],   '%Y-%m-%d').date()
        self.assertAlmostEqual((end - start).days, 45, delta=1)

    def test_coverage_days_clamped_low(self):
        mock = _mock_requests([_page([])])
        with unittest.mock.patch.object(_mod, "requests", mock):
            _ConcreteAdapter().fetch(coverage_days=2)
        params = mock.get.call_args_list[0].kwargs.get('params', {})
        start = datetime.datetime.strptime(params['start_date'][:10], '%Y-%m-%d').date()
        end   = datetime.datetime.strptime(params['end_date'][:10],   '%Y-%m-%d').date()
        self.assertGreaterEqual((end - start).days, 7)

    def test_coverage_days_clamped_high(self):
        mock = _mock_requests([_page([])])
        with unittest.mock.patch.object(_mod, "requests", mock):
            _ConcreteAdapter().fetch(coverage_days=999)
        params = mock.get.call_args_list[0].kwargs.get('params', {})
        start = datetime.datetime.strptime(params['start_date'][:10], '%Y-%m-%d').date()
        end   = datetime.datetime.strptime(params['end_date'][:10],   '%Y-%m-%d').date()
        self.assertLessEqual((end - start).days, 180)

    def test_coverage_days_invalid_falls_back_to_60(self):
        mock = _mock_requests([_page([])])
        with unittest.mock.patch.object(_mod, "requests", mock):
            _ConcreteAdapter().fetch(coverage_days=None)
        params = mock.get.call_args_list[0].kwargs.get('params', {})
        start = datetime.datetime.strptime(params['start_date'][:10], '%Y-%m-%d').date()
        end   = datetime.datetime.strptime(params['end_date'][:10],   '%Y-%m-%d').date()
        self.assertAlmostEqual((end - start).days, 60, delta=1)

    def test_per_page_is_100(self):
        mock = _mock_requests([_page([])])
        with unittest.mock.patch.object(_mod, "requests", mock):
            _ConcreteAdapter().fetch()
        params = mock.get.call_args_list[0].kwargs.get('params', {})
        self.assertEqual(params.get('per_page'), _mod._PER_PAGE)

    def test_only_published_events(self):
        mock = _mock_requests([_page([])])
        with unittest.mock.patch.object(_mod, "requests", mock):
            _ConcreteAdapter().fetch()
        params = mock.get.call_args_list[0].kwargs.get('params', {})
        self.assertEqual(params.get('status'), 'publish')

    def test_endpoint_uses_api_base(self):
        mock = _mock_requests([_page([])])
        with unittest.mock.patch.object(_mod, "requests", mock):
            _ConcreteAdapter().fetch()
        called_url = mock.get.call_args_list[0].args[0]
        self.assertIn("example.org", called_url)
        self.assertIn("tribe/events/v1/events", called_url)

    def test_result_has_expected_keys(self):
        mock = _mock_requests([_page([_make_ev(id=1)])])
        with unittest.mock.patch.object(_mod, "requests", mock):
            result = _ConcreteAdapter().fetch()
        self.assertEqual(len(result), 1)
        r = result[0]
        for key in ('source_key', 'title', 'start_datetime', 'source_url',
                    'normalized_fingerprint', 'raw_source_json'):
            self.assertIn(key, r, f"Missing key: {key}")

    def test_source_key_propagated(self):
        mock = _mock_requests([_page([_make_ev(id=1)])])
        with unittest.mock.patch.object(_mod, "requests", mock):
            result = _ConcreteAdapter().fetch()
        self.assertEqual(result[0]["source_key"], "test_source")


if __name__ == "__main__":
    unittest.main()
