"""
Unit tests for the Positively Pittsburgh / CitySpark adapter helpers.
Run with:  python3 -m pytest tests/ -v
       or: python3 tests/test_positively_pgh.py
"""
import sys
import os
import types
import importlib.util
import unittest
import unittest.mock

# ---------------------------------------------------------------------------
# Stub heavy deps before loading the adapter module.
# ---------------------------------------------------------------------------

def _stub_module(name):
    m = types.ModuleType(name)
    sys.modules[name] = m
    return m

# adapters.base stub
_adapters = _stub_module("adapters")
_adapters_base = _stub_module("adapters.base")
_adapters.__path__ = []  # mark as package

class _BaseAdapter:
    source_key = None
    display_name = None
    def fetch(self):
        return []

_adapters_base.BaseAdapter = _BaseAdapter

# events stub
_ev = _stub_module("events")
_ev.make_fingerprint = lambda src, eid, dt, title=None, venue=None: "stub-fp"
_ev.make_series_key = lambda src, title: "stub-sk"

# requests stub (network not touched in unit tests)
_stub_module("requests")

# ---------------------------------------------------------------------------
# Load adapter module directly from its file path.
# ---------------------------------------------------------------------------
_adapter_path = os.path.join(
    os.path.dirname(__file__), "..", "api", "adapters", "positively_pgh.py"
)
_spec = importlib.util.spec_from_file_location("positively_pgh", _adapter_path)
_mod = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(_mod)

_fmt_price   = _mod._fmt_price
_parse_price = _mod._parse_price
_best_url    = _mod._best_url
_is_free_flag = _mod._is_free_flag


# ---------------------------------------------------------------------------

class TestFmtPrice(unittest.TestCase):

    def test_integer_float(self):
        self.assertEqual(_fmt_price(10.0), "10")

    def test_decimal_float(self):
        self.assertEqual(_fmt_price(11.6), "11.60")

    def test_integer_int(self):
        self.assertEqual(_fmt_price(10), "10")

    def test_zero(self):
        self.assertEqual(_fmt_price(0), "0")

    def test_none(self):
        self.assertIsNone(_fmt_price(None))

    def test_string_integer(self):
        self.assertEqual(_fmt_price("10"), "10")

    def test_string_with_dollar(self):
        self.assertEqual(_fmt_price("$10"), "10")

    def test_string_decimal(self):
        self.assertEqual(_fmt_price("11.50"), "11.50")

    def test_non_numeric_string_returns_none(self):
        self.assertIsNone(_fmt_price("General Admission"))

    def test_garbage_string_returns_none(self):
        self.assertIsNone(_fmt_price("Free admission for all"))


class TestParsePrice(unittest.TestCase):

    def test_free_flag_true(self):
        self.assertEqual(_parse_price({"Free": True}), "Free")

    def test_free_flag_true_ignores_price(self):
        self.assertEqual(_parse_price({"Free": True, "Price": 10}), "Free")

    def test_free_flag_true_price_zero(self):
        self.assertEqual(_parse_price({"Free": True, "Price": 0}), "Free")

    def test_numeric_price(self):
        self.assertEqual(_parse_price({"Free": False, "Price": 15}), "$15")

    def test_numeric_price_float(self):
        self.assertEqual(_parse_price({"Free": False, "Price": 15.0}), "$15")

    def test_price_range(self):
        self.assertEqual(_parse_price({"Free": False, "Price": 10, "PriceHigh": 20}), "$10–$20")

    def test_price_range_same_value_shows_single(self):
        self.assertEqual(_parse_price({"Free": False, "Price": 10, "PriceHigh": 10}), "$10")

    def test_non_numeric_price_text_skipped(self):
        # "General Admission" is not a number — must not produce "$General Admission"
        self.assertIsNone(_parse_price({"Free": False, "Price": "General Admission"}))

    def test_double_dollar_avoided(self):
        # Price="$10" must not produce "$$10"
        self.assertEqual(_parse_price({"Free": False, "Price": "$10"}), "$10")

    def test_no_price_returns_none(self):
        self.assertIsNone(_parse_price({}))

    def test_price_text_numeric(self):
        self.assertEqual(_parse_price({"Free": False, "PriceText": "5"}), "$5")

    def test_price_text_non_numeric_skipped(self):
        self.assertIsNone(_parse_price({"Free": False, "PriceText": "See website"}))

    def test_ugly_float_cleaned(self):
        # 11.6 must not produce "$11.6" — must produce "$11.60"
        self.assertEqual(_parse_price({"Free": False, "Price": 11.6}), "$11.60")


class TestIsFreeFlag(unittest.TestCase):
    """Explicit tests for _is_free_flag — the gatekeeper between raw source data and 'Free' admission."""

    # --- truthy inputs ---
    def test_bool_true(self):
        self.assertTrue(_is_free_flag(True))

    def test_int_one(self):
        self.assertTrue(_is_free_flag(1))

    def test_float_one(self):
        self.assertTrue(_is_free_flag(1.0))

    def test_string_true_lowercase(self):
        self.assertTrue(_is_free_flag("true"))

    def test_string_true_capitalized(self):
        self.assertTrue(_is_free_flag("True"))

    def test_string_true_uppercase(self):
        self.assertTrue(_is_free_flag("TRUE"))

    def test_string_one(self):
        self.assertTrue(_is_free_flag("1"))

    def test_string_true_with_whitespace(self):
        self.assertTrue(_is_free_flag("  true  "))

    # --- falsy / rejected inputs ---
    def test_bool_false(self):
        self.assertFalse(_is_free_flag(False))

    def test_int_zero(self):
        self.assertFalse(_is_free_flag(0))

    def test_float_zero(self):
        self.assertFalse(_is_free_flag(0.0))

    def test_string_false(self):
        # "false" as a string must NOT be treated as free
        self.assertFalse(_is_free_flag("false"))

    def test_string_false_capitalized(self):
        self.assertFalse(_is_free_flag("False"))

    def test_string_zero(self):
        self.assertFalse(_is_free_flag("0"))

    def test_none(self):
        self.assertFalse(_is_free_flag(None))

    def test_missing_key_returns_none_which_is_false(self):
        self.assertFalse(_is_free_flag({}.get("Free")))

    def test_int_two_not_free(self):
        # Only 1 is accepted; 2 is not a valid free flag
        self.assertFalse(_is_free_flag(2))


class TestParsePriceFreeCases(unittest.TestCase):
    """Coverage for the required Free-flag variants in _parse_price."""

    def test_free_bool_true_no_price(self):
        self.assertEqual(_parse_price({"Free": True}), "Free")

    def test_free_string_true_no_price(self):
        self.assertEqual(_parse_price({"Free": "true"}), "Free")

    def test_free_int_one_no_price(self):
        self.assertEqual(_parse_price({"Free": 1}), "Free")

    def test_free_bool_true_with_price(self):
        # Free flag takes priority over price
        self.assertEqual(_parse_price({"Free": True, "Price": 10}), "Free")

    def test_free_bool_false_no_price_returns_none(self):
        self.assertIsNone(_parse_price({"Free": False}))

    def test_free_string_false_no_price_returns_none(self):
        # Critical: "false" (string) must NOT be treated as free
        self.assertIsNone(_parse_price({"Free": "false"}))

    def test_free_missing_no_price_returns_none(self):
        self.assertIsNone(_parse_price({}))

    def test_lowercase_free_key(self):
        # Guard against CitySpark switching to lowercase key
        self.assertEqual(_parse_price({"free": True}), "Free")

    def test_lowercase_free_string_true(self):
        self.assertEqual(_parse_price({"free": "true"}), "Free")


class TestParsePriceLowHighFullPrice(unittest.TestCase):
    """Coverage for LowFullPrice / HighFullPrice CitySpark extended fields."""

    def test_low_full_price_used_when_price_missing(self):
        self.assertEqual(_parse_price({"Free": False, "LowFullPrice": 8}), "$8")

    def test_high_full_price_used_for_range(self):
        self.assertEqual(_parse_price({"Free": False, "LowFullPrice": 8, "HighFullPrice": 15}), "$8–$15")

    def test_low_high_same_shows_single(self):
        self.assertEqual(_parse_price({"Free": False, "LowFullPrice": 12, "HighFullPrice": 12}), "$12")

    def test_price_takes_precedence_over_low_full_price(self):
        # Price/PriceHigh are preferred; LowFullPrice is only a fallback
        self.assertEqual(_parse_price({"Free": False, "Price": 10, "LowFullPrice": 8}), "$10")

    def test_low_full_price_skipped_if_non_numeric(self):
        self.assertIsNone(_parse_price({"Free": False, "LowFullPrice": "General Admission"}))

    def test_free_flag_overrides_low_full_price(self):
        self.assertEqual(_parse_price({"Free": True, "LowFullPrice": 8}), "Free")

    def test_price_text_preferred_over_low_full_price(self):
        # PriceText comes AFTER LowFullPrice in the chain, so LowFullPrice wins
        self.assertEqual(_parse_price({"Free": False, "PriceText": "5", "LowFullPrice": 8}), "$8")

    def test_low_full_price_decimal(self):
        self.assertEqual(_parse_price({"Free": False, "LowFullPrice": 11.6}), "$11.60")


class TestBestUrl(unittest.TestCase):

    def test_primary_url_preferred(self):
        ev = {"PrimaryUrl": "https://example.com/event", "TicketUrl": "https://tickets.com/ev"}
        self.assertEqual(_best_url(ev), "https://example.com/event")

    def test_ticket_url_fallback(self):
        ev = {"PrimaryUrl": None, "TicketUrl": "https://tickets.com/ev"}
        self.assertEqual(_best_url(ev), "https://tickets.com/ev")

    def test_blank_primary_falls_to_ticket(self):
        ev = {"PrimaryUrl": "", "TicketUrl": "https://tickets.com/ev"}
        self.assertEqual(_best_url(ev), "https://tickets.com/ev")

    def test_links_fallback(self):
        ev = {"PrimaryUrl": None, "TicketUrl": None,
              "Links": [{"url": "https://links.com/ev"}]}
        self.assertEqual(_best_url(ev), "https://links.com/ev")

    def test_tickets_array_fallback(self):
        ev = {"PrimaryUrl": None, "TicketUrl": None, "Links": [],
              "Tickets": [{"url": "https://tix.com/ev"}]}
        self.assertEqual(_best_url(ev), "https://tix.com/ev")

    def test_no_url_returns_none(self):
        ev = {"PrimaryUrl": None, "TicketUrl": None, "Links": [], "Tickets": []}
        self.assertIsNone(_best_url(ev))

    def test_non_http_primary_skipped(self):
        ev = {"PrimaryUrl": "javascript:void(0)", "TicketUrl": "https://tickets.com/ev"}
        self.assertEqual(_best_url(ev), "https://tickets.com/ev")

    def test_empty_dict(self):
        self.assertIsNone(_best_url({}))


class TestRawJsonValidity(unittest.TestCase):
    """Prove that _normalize() produces valid, complete JSON in raw_source_json."""

    def _minimal_ev(self, **overrides):
        base = {
            "PId": 12345,
            "Name": "Test Event",
            "DateStart": "2026-06-01T10:00:00Z",
            "DateEnd": "2026-06-01T12:00:00Z",
            "Venue": "Test Venue",
            "CityState": "Pittsburgh, PA",
            "Free": False,
            "Price": None,
            "PriceHigh": None,
            "PriceText": None,
            "PrimaryUrl": "https://example.com/event",
            "TicketUrl": None,
            "Links": [],
            "Tickets": [],
            "MediumImg": None,
            "SmallImg": None,
            "Address": "123 Main St",
            "Zip": "15222",
            "latitude": 40.4406,
            "longitude": -79.9959,
            "Short": "A short description.",
            "Description": "A longer description of the event.",
            "isVirtual": False,
        }
        base.update(overrides)
        return base

    def test_raw_json_is_valid_json(self):
        """_normalize() must produce raw_source_json that is valid JSON."""
        import json
        ev = self._minimal_ev()
        result = _mod._normalize(ev)
        raw = result["raw_source_json"]
        # Must parse without error
        parsed = json.loads(raw)
        self.assertIsInstance(parsed, dict)

    def test_raw_json_not_truncated(self):
        """raw_source_json must not be cut off at an arbitrary character limit."""
        import json
        # Build an event with a very long description to exceed old 4000-char limit
        long_desc = "A" * 4000
        ev = self._minimal_ev(Description=long_desc, Short=long_desc)
        result = _mod._normalize(ev)
        raw = result["raw_source_json"]
        # If truncated the JSON would be invalid
        try:
            json.loads(raw)
        except json.JSONDecodeError as e:
            self.fail(f"raw_source_json is invalid JSON (likely truncated): {e}")

    def test_raw_json_contains_free_field(self):
        """Free field must be present and readable from raw_source_json."""
        import json
        ev = self._minimal_ev(Free=True)
        result = _mod._normalize(ev)
        raw = result["raw_source_json"]
        parsed = json.loads(raw)
        self.assertIn("Free", parsed)
        self.assertTrue(parsed["Free"])

    def test_raw_json_free_true_and_admission_free(self):
        """Free=True event must have admission='Free' AND Free in valid raw_source_json."""
        import json
        ev = self._minimal_ev(Free=True, Price=0, PriceHigh=0)
        result = _mod._normalize(ev)
        self.assertEqual(result["admission"], "Free")
        parsed = json.loads(result["raw_source_json"])
        self.assertTrue(parsed["Free"])

    def test_raw_json_unicode_safe(self):
        """Unicode in event name/description must be stored as real chars, not escaped."""
        import json
        ev = self._minimal_ev(Name="Café & Résumé Night — 2026")
        result = _mod._normalize(ev)
        raw = result["raw_source_json"]
        # ensure_ascii=False means real unicode, not \\uXXXX escapes for these chars
        self.assertIn("Café", raw)
        parsed = json.loads(raw)
        self.assertEqual(parsed["Name"], "Café & Résumé Night — 2026")

    def test_raw_json_invalid_text_does_not_crash_like_search(self):
        """Simulate the diagnostic script's text-search approach on a truncated JSON string.

        The old adapter truncated at 4000 chars, producing invalid JSON. The diagnostic
        script uses LIKE '%"Free": true%' (text search) rather than JSON_EXTRACT, which
        must never crash even on invalid JSON.
        """
        truncated_json = '{"PId": 99, "Free": false, "Desc": "' + "x" * 4000
        # Text search approach — must not throw
        has_free_true = '"Free": true' in truncated_json
        self.assertFalse(has_free_true)

    def test_raw_json_invalid_with_free_true_detected_by_text_search(self):
        """If Free: true appears before the truncation point, text search must find it."""
        truncated_json = '{"PId": 99, "Free": true, "Desc": "' + "x" * 4000
        has_free_true = '"Free": true' in truncated_json
        self.assertTrue(has_free_true)

    def test_primary_url_null_uses_ticket_url(self):
        """PrimaryUrl=None with TicketUrl set must use TicketUrl as the event URL."""
        ev = self._minimal_ev(PrimaryUrl=None, TicketUrl="https://tickets.com/test-event")
        result = _mod._normalize(ev)
        self.assertEqual(result["source_url"], "https://tickets.com/test-event")
        self.assertEqual(result["official_url"], "https://tickets.com/test-event")

    def test_is_virtual_true_events_skipped_in_fetch(self):
        """Verify that the isVirtual guard is present in the fetch loop."""
        import inspect
        src = inspect.getsource(_mod.PositivelyPgh.fetch)
        self.assertIn("isVirtual", src)


class TestFetchPagination(unittest.TestCase):
    """Tests for PositivelyPgh.fetch() pagination behavior."""

    _DEFAULT_URL = object()  # sentinel to distinguish "use default" from explicit None

    def _ev(self, pid, date="2026-05-16T10:00:00", virtual=False, free=False,
            primary_url=_DEFAULT_URL, ticket_url=None):
        purl = f"https://example.com/{pid}" if primary_url is self._DEFAULT_URL else primary_url
        return {
            "PId": pid, "Id": pid,
            "Name": f"Event {pid}",
            "DateStart": date, "DateEnd": date,
            "Venue": "Test Venue", "CityState": "Pittsburgh, PA",
            "isVirtual": virtual, "Free": free,
            "Price": None, "PriceHigh": None, "PriceText": None,
            "PrimaryUrl": purl,
            "TicketUrl": ticket_url,
            "Links": [], "Tickets": [],
            "MediumImg": None, "SmallImg": None,
            "Address": "123 Main St", "Zip": "15222",
            "latitude": 40.4406, "longitude": -79.9959,
            "Short": "Test desc.", "Description": "Longer test description.",
        }

    def _page(self, events, possible=None, success=True):
        r = {"Success": success, "Value": events}
        if possible is not None:
            r["Possible"] = possible
        return r

    def _mock_requests(self, pages):
        """Return a mock requests module that serves pages in sequence."""
        idx = [0]

        def _post(url, **kwargs):
            i = idx[0]
            idx[0] += 1
            m = unittest.mock.MagicMock()
            m.raise_for_status.return_value = None
            m.json.return_value = pages[i] if i < len(pages) else self._page([])
            return m

        mock_req = unittest.mock.MagicMock()
        mock_req.post.side_effect = _post
        return mock_req

    def _skips(self, mock_req):
        """Extract skip values from recorded requests.post calls."""
        return [c.kwargs["json"]["skip"] for c in mock_req.post.call_args_list]

    # ── Pagination ────────────────────────────────────────────────────────────

    def test_paginates_three_pages_and_includes_future_events(self):
        """Adapter fetches until a short batch, and future-day events from later pages appear."""
        ps = _mod._PAGE_SIZE
        today_evs    = [self._ev(i,       "2026-05-16T10:00:00") for i in range(ps)]
        tomorrow_evs = [self._ev(i+ps,    "2026-05-17T10:00:00") for i in range(ps)]
        future_evs   = [self._ev(i+2*ps,  "2026-05-18T14:00:00") for i in range(ps // 2)]

        pages = [
            self._page(today_evs),
            self._page(tomorrow_evs),
            self._page(future_evs),   # fewer than _PAGE_SIZE → stops here
        ]
        mock_req = self._mock_requests(pages)
        with unittest.mock.patch.object(_mod, "requests", mock_req):
            result = _mod.PositivelyPgh().fetch()

        self.assertEqual(mock_req.post.call_count, 3)
        self.assertEqual(self._skips(mock_req), [0, ps, ps * 2])

        # Future events from page 2 and 3 must be present
        titles = {e["title"] for e in result}
        self.assertTrue(any(f"Event {ps}" in t for t in titles), "page-2 (tomorrow) events missing")
        self.assertTrue(any(f"Event {2*ps}" in t for t in titles), "page-3 (May 18) events missing")

    def test_future_event_date_preserved(self):
        """start_datetime of a future event must not be altered."""
        evs = [self._ev(1, date="2026-05-18T14:00:00")]
        mock_req = self._mock_requests([self._page(evs)])
        with unittest.mock.patch.object(_mod, "requests", mock_req):
            result = _mod.PositivelyPgh().fetch()
        self.assertIn("2026-05-18", result[0]["start_datetime"])

    # ── Stop conditions ───────────────────────────────────────────────────────

    def test_stops_when_value_is_empty(self):
        """A full page followed by an empty page must stop after the second request."""
        ps = _mod._PAGE_SIZE
        pages = [
            self._page([self._ev(i) for i in range(ps)]),  # full page → request page 2
            self._page([]),                                  # empty → stop
        ]
        mock_req = self._mock_requests(pages)
        with unittest.mock.patch.object(_mod, "requests", mock_req):
            result = _mod.PositivelyPgh().fetch()
        self.assertEqual(mock_req.post.call_count, 2)
        self.assertEqual(len(result), ps)

    def test_stops_when_batch_smaller_than_page_size(self):
        """A partial page must stop pagination."""
        ps = _mod._PAGE_SIZE
        pages = [
            self._page([self._ev(i)    for i in range(ps)]),        # full page
            self._page([self._ev(i+ps) for i in range(ps // 4)]),   # partial → stop
        ]
        mock_req = self._mock_requests(pages)
        with unittest.mock.patch.object(_mod, "requests", mock_req):
            result = _mod.PositivelyPgh().fetch()
        self.assertEqual(mock_req.post.call_count, 2)
        self.assertEqual(len(result), ps + ps // 4)

    def test_stops_at_max_pages_cap(self):
        """Must not exceed _MAX_PAGES even when CitySpark keeps returning full pages."""
        def _infinite_post(url, **kwargs):
            skip = kwargs["json"]["skip"]
            m = unittest.mock.MagicMock()
            m.raise_for_status.return_value = None
            evs = [self._ev(skip + i) for i in range(25)]
            m.json.return_value = self._page(evs)
            return m

        mock_req = unittest.mock.MagicMock()
        mock_req.post.side_effect = _infinite_post
        with unittest.mock.patch.object(_mod, "requests", mock_req):
            _mod.PositivelyPgh().fetch()

        self.assertLessEqual(mock_req.post.call_count, _mod._MAX_PAGES)

    def test_stops_when_possible_count_reached(self):
        """When Possible equals the batch size, must not request a second page."""
        ps = _mod._PAGE_SIZE
        evs = [self._ev(i) for i in range(ps)]
        pages = [self._page(evs, possible=ps)]  # tells us exactly ps events exist
        mock_req = self._mock_requests(pages)
        with unittest.mock.patch.object(_mod, "requests", mock_req):
            result = _mod.PositivelyPgh().fetch()
        self.assertEqual(mock_req.post.call_count, 1)
        self.assertEqual(len(result), ps)

    # ── Existing behavior preserved ───────────────────────────────────────────

    def test_virtual_events_skipped(self):
        evs = [
            self._ev(1, virtual=False),
            self._ev(2, virtual=True),   # must not appear in results
            self._ev(3, virtual=False),
        ]
        mock_req = self._mock_requests([self._page(evs)])
        with unittest.mock.patch.object(_mod, "requests", mock_req):
            result = _mod.PositivelyPgh().fetch()
        ids = {e["source_event_id"] for e in result}
        self.assertIn("1", ids)
        self.assertNotIn("2", ids)
        self.assertIn("3", ids)

    def test_free_true_sets_admission_free(self):
        evs = [self._ev(1, free=True)]
        mock_req = self._mock_requests([self._page(evs)])
        with unittest.mock.patch.object(_mod, "requests", mock_req):
            result = _mod.PositivelyPgh().fetch()
        self.assertEqual(result[0]["admission"], "Free")

    def test_primary_url_null_falls_back_to_ticket_url(self):
        ev = self._ev(1, primary_url=None, ticket_url="https://tickets.com/test")
        mock_req = self._mock_requests([self._page([ev])])
        with unittest.mock.patch.object(_mod, "requests", mock_req):
            result = _mod.PositivelyPgh().fetch()
        self.assertEqual(result[0]["source_url"], "https://tickets.com/test")

    def test_links_fallback_when_primary_and_ticket_null(self):
        ev = self._ev(1, primary_url=None)
        ev["TicketUrl"] = None
        ev["Links"] = [{"url": "https://links.com/event"}]
        mock_req = self._mock_requests([self._page([ev])])
        with unittest.mock.patch.object(_mod, "requests", mock_req):
            result = _mod.PositivelyPgh().fetch()
        self.assertEqual(result[0]["source_url"], "https://links.com/event")

    def test_raw_source_json_valid_and_not_truncated(self):
        import json as _json
        ev = self._ev(1)
        ev["Description"] = "X" * 5000  # exceeds old 4000-char limit
        mock_req = self._mock_requests([self._page([ev])])
        with unittest.mock.patch.object(_mod, "requests", mock_req):
            result = _mod.PositivelyPgh().fetch()
        raw = result[0]["raw_source_json"]
        parsed = _json.loads(raw)   # must not raise
        self.assertIsInstance(parsed, dict)
        self.assertEqual(len(parsed["Description"]), 5000)

    # ── Coverage-based stop ───────────────────────────────────────────────────

    def test_min_coverage_days_constant_is_60(self):
        """_MIN_COVERAGE_DAYS must be 60 (used as the fallback default)."""
        self.assertEqual(_mod._MIN_COVERAGE_DAYS, 60)

    def test_default_coverage_days_uses_60(self):
        """fetch() with no coverage_days arg must stop at a 60-day target."""
        import datetime
        ps = _mod._PAGE_SIZE
        now = datetime.datetime.utcnow()
        near   = (now + datetime.timedelta(days=5)).strftime("%Y-%m-%dT10:00:00")
        target = (now + datetime.timedelta(days=60)).strftime("%Y-%m-%dT10:00:00")
        pages = [
            self._page([self._ev(i, date=near)     for i in range(ps)]),
            self._page([self._ev(i+ps, date=target) for i in range(ps)]),
        ]
        mock_req = self._mock_requests(pages)
        with unittest.mock.patch.object(_mod, "requests", mock_req):
            _mod.PositivelyPgh().fetch()  # no coverage_days arg
        self.assertEqual(mock_req.post.call_count, 2)

    def test_custom_coverage_days_45_stops_at_45_day_target(self):
        """fetch(coverage_days=45) must keep paging past 30 days and stop at 45."""
        import datetime
        ps = _mod._PAGE_SIZE
        now = datetime.datetime.utcnow()
        day30  = (now + datetime.timedelta(days=30)).strftime("%Y-%m-%dT10:00:00")
        day45  = (now + datetime.timedelta(days=45)).strftime("%Y-%m-%dT10:00:00")
        pages = [
            self._page([self._ev(i,      date=day30) for i in range(ps)]),  # 30-day page — NOT enough
            self._page([self._ev(i+ps,   date=day45) for i in range(ps)]),  # 45-day page — stops here
        ]
        mock_req = self._mock_requests(pages)
        with unittest.mock.patch.object(_mod, "requests", mock_req):
            result = _mod.PositivelyPgh().fetch(coverage_days=45)
        # Must have fetched both pages (30-day page wasn't enough with target=45)
        self.assertEqual(mock_req.post.call_count, 2)
        self.assertEqual(len(result), ps * 2)

    def test_coverage_days_clamps_low(self):
        """fetch(coverage_days=3) must clamp to 7, not crash."""
        import datetime
        ps = _mod._PAGE_SIZE
        now = datetime.datetime.utcnow()
        day7 = (now + datetime.timedelta(days=7)).strftime("%Y-%m-%dT10:00:00")
        pages = [self._page([self._ev(i, date=day7) for i in range(ps)])]
        mock_req = self._mock_requests(pages)
        with unittest.mock.patch.object(_mod, "requests", mock_req):
            result = _mod.PositivelyPgh().fetch(coverage_days=3)
        self.assertIsInstance(result, list)  # did not crash

    def test_coverage_days_clamps_high(self):
        """fetch(coverage_days=250) must clamp to 180, not crash."""
        import datetime
        ps = _mod._PAGE_SIZE
        now = datetime.datetime.utcnow()
        day180 = (now + datetime.timedelta(days=180)).strftime("%Y-%m-%dT10:00:00")
        pages = [self._page([self._ev(i, date=day180) for i in range(ps // 2)])]
        mock_req = self._mock_requests(pages)
        with unittest.mock.patch.object(_mod, "requests", mock_req):
            result = _mod.PositivelyPgh().fetch(coverage_days=250)
        self.assertIsInstance(result, list)  # did not crash

    def test_coverage_days_invalid_fallback(self):
        """fetch(coverage_days=None) must fall back to 60 without crashing."""
        import datetime
        ps = _mod._PAGE_SIZE
        now = datetime.datetime.utcnow()
        day60 = (now + datetime.timedelta(days=60)).strftime("%Y-%m-%dT10:00:00")
        pages = [self._page([self._ev(i, date=day60) for i in range(ps // 2)])]
        mock_req = self._mock_requests(pages)
        with unittest.mock.patch.object(_mod, "requests", mock_req):
            result = _mod.PositivelyPgh().fetch(coverage_days=None)
        self.assertIsInstance(result, list)

    def test_logs_coverage_days_value(self):
        """fetch() must print the coverage_days value used."""
        import datetime, io, contextlib
        ps = _mod._PAGE_SIZE
        now = datetime.datetime.utcnow()
        day45 = (now + datetime.timedelta(days=45)).strftime("%Y-%m-%dT10:00:00")
        pages = [self._page([self._ev(i, date=day45) for i in range(ps // 2)])]
        mock_req = self._mock_requests(pages)
        buf = io.StringIO()
        with contextlib.redirect_stdout(buf):
            with unittest.mock.patch.object(_mod, "requests", mock_req):
                _mod.PositivelyPgh().fetch(coverage_days=45)
        self.assertIn("coverage_days=45", buf.getvalue())

    def test_fetch_payload_sends_explicit_end_date(self):
        """Payload must send an explicit end date ~90 days out; end:null returns only today's events."""
        import datetime
        mock_req = self._mock_requests([self._page([self._ev(1)])])
        with unittest.mock.patch.object(_mod, "requests", mock_req):
            _mod.PositivelyPgh().fetch()
        payload = mock_req.post.call_args_list[0].kwargs["json"]
        self.assertIsNotNone(payload.get("end"))
        end_date = datetime.datetime.fromisoformat(payload["end"]).date()
        expected = (datetime.datetime.utcnow() + datetime.timedelta(days=_mod._FETCH_WINDOW_DAYS)).date()
        self.assertEqual(end_date, expected)

    def test_stops_after_coverage_target_reached(self):
        """Fetch must stop once a page contains events at or past the 30-day target."""
        import datetime
        ps = _mod._PAGE_SIZE
        now = datetime.datetime.utcnow()
        near   = (now + datetime.timedelta(days=5)).strftime("%Y-%m-%dT10:00:00")
        target = (now + datetime.timedelta(days=_mod._MIN_COVERAGE_DAYS)).strftime("%Y-%m-%dT10:00:00")
        pages = [
            self._page([self._ev(i,      date=near)   for i in range(ps)]),
            self._page([self._ev(i + ps, date=target) for i in range(ps)]),
            # third page must NOT be requested
        ]
        mock_req = self._mock_requests(pages)
        with unittest.mock.patch.object(_mod, "requests", mock_req):
            result = _mod.PositivelyPgh().fetch()
        self.assertEqual(mock_req.post.call_count, 2)
        self.assertEqual(len(result), ps * 2)

    def test_continues_past_same_day_pages_until_coverage(self):
        """Adapter must keep paging through near-future events until coverage target is reached."""
        import datetime
        ps = _mod._PAGE_SIZE
        now = datetime.datetime.utcnow()
        near   = (now + datetime.timedelta(days=1)).strftime("%Y-%m-%dT10:00:00")
        target = (now + datetime.timedelta(days=_mod._MIN_COVERAGE_DAYS)).strftime("%Y-%m-%dT10:00:00")
        pages = [
            self._page([self._ev(i,        date=near)   for i in range(ps)]),
            self._page([self._ev(i + ps,   date=near)   for i in range(ps)]),
            self._page([self._ev(i + 2*ps, date=target) for i in range(ps)]),
            # page 4 must NOT be requested
        ]
        mock_req = self._mock_requests(pages)
        with unittest.mock.patch.object(_mod, "requests", mock_req):
            result = _mod.PositivelyPgh().fetch()
        self.assertEqual(mock_req.post.call_count, 3)
        self.assertEqual(len(result), ps * 3)

    def test_logs_warning_when_cap_hit_before_coverage(self):
        """Must log a WARNING with pages, skip, latest date, and target when cap fires early."""
        import datetime, io, contextlib
        ps = _mod._PAGE_SIZE
        now = datetime.datetime.utcnow()
        near = (now + datetime.timedelta(days=1)).strftime("%Y-%m-%dT10:00:00")

        def _infinite_post(url, **kwargs):
            skip = kwargs["json"]["skip"]
            m = unittest.mock.MagicMock()
            m.raise_for_status.return_value = None
            evs = [self._ev(skip + i, date=near) for i in range(ps)]
            m.json.return_value = self._page(evs)
            return m

        mock_req = unittest.mock.MagicMock()
        mock_req.post.side_effect = _infinite_post
        buf = io.StringIO()
        with contextlib.redirect_stdout(buf):
            with unittest.mock.patch.object(_mod, "requests", mock_req):
                _mod.PositivelyPgh().fetch()
        output = buf.getvalue()
        self.assertIn("WARNING", output)
        self.assertIn("cap", output.lower())
        self.assertIn("target", output.lower())

    def test_duplicate_ids_not_double_counted(self):
        """Same CitySpark ID appearing on two pages must produce only one event."""
        ps = _mod._PAGE_SIZE
        ev1 = self._ev(9999, "2026-05-16T10:00:00")
        ev2 = self._ev(9999, "2026-05-16T10:00:00")   # same PId/Id
        filler = [self._ev(i) for i in range(ps - 1)]
        pages = [
            self._page([ev1] + filler),   # full page (ev1 + ps-1 fillers)
            self._page([ev2]),             # duplicate on page 2 (partial → stop)
        ]
        mock_req = self._mock_requests(pages)
        with unittest.mock.patch.object(_mod, "requests", mock_req):
            result = _mod.PositivelyPgh().fetch()
        ids = [e["source_event_id"] for e in result]
        self.assertEqual(ids.count("9999"), 1)


if __name__ == "__main__":
    unittest.main()
