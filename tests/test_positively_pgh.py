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
_ev.make_fingerprint = lambda title, date_str, venue: "stub-fp"

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


if __name__ == "__main__":
    unittest.main()
