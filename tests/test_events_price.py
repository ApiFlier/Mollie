"""
Unit tests for price normalization and filtering in events.py.
Run with:  python3 -m pytest tests/ -v
       or: python3 tests/test_events_price.py
"""
import sys
import os
import importlib.util
import unittest

# Load events.py directly — it only uses stdlib, no stubs needed.
_events_path = os.path.join(os.path.dirname(__file__), "..", "api", "events.py")
_spec = importlib.util.spec_from_file_location("events_module", _events_path)
_events_mod = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(_events_mod)

_parse_admission_price = _events_mod._parse_admission_price
_filter_by_price       = _events_mod._filter_by_price
_enrich_event          = _events_mod._enrich_event


# ---------------------------------------------------------------------------

class TestParseAdmissionPrice(unittest.TestCase):

    def test_none_is_unknown(self):
        r = _parse_admission_price(None)
        self.assertFalse(r["is_free"])
        self.assertIsNone(r["price_min"])
        self.assertIsNone(r["price_max"])
        self.assertEqual(r["price_status"], "unknown")

    def test_free_string(self):
        r = _parse_admission_price("Free")
        self.assertTrue(r["is_free"])
        self.assertEqual(r["price_min"], 0.0)
        self.assertEqual(r["price_max"], 0.0)
        self.assertEqual(r["price_status"], "free")

    def test_free_case_insensitive(self):
        r = _parse_admission_price("free")
        self.assertTrue(r["is_free"])
        self.assertEqual(r["price_status"], "free")

    def test_single_price_with_dollar(self):
        r = _parse_admission_price("$15")
        self.assertFalse(r["is_free"])
        self.assertEqual(r["price_min"], 15.0)
        self.assertEqual(r["price_max"], 15.0)
        self.assertEqual(r["price_status"], "listed")

    def test_single_price_without_dollar(self):
        r = _parse_admission_price("5")
        self.assertEqual(r["price_min"], 5.0)
        self.assertEqual(r["price_status"], "listed")

    def test_price_range(self):
        r = _parse_admission_price("$10–$20")  # en dash
        self.assertFalse(r["is_free"])
        self.assertEqual(r["price_min"], 10.0)
        self.assertEqual(r["price_max"], 20.0)
        self.assertEqual(r["price_status"], "listed")

    def test_decimal_price(self):
        r = _parse_admission_price("$11.50")
        self.assertEqual(r["price_min"], 11.50)
        self.assertEqual(r["price_max"], 11.50)
        self.assertEqual(r["price_status"], "listed")

    def test_zero_price(self):
        r = _parse_admission_price("$0")
        self.assertFalse(r["is_free"])  # $0 is not the same as "Free"
        self.assertEqual(r["price_min"], 0.0)
        self.assertEqual(r["price_status"], "listed")


class TestEnrichEvent(unittest.TestCase):

    def test_free_event_enriched(self):
        ev = {"admission": "Free"}
        _enrich_event(ev)
        self.assertTrue(ev["is_free"])
        self.assertEqual(ev["price_status"], "free")

    def test_paid_event_enriched(self):
        ev = {"admission": "$20"}
        _enrich_event(ev)
        self.assertFalse(ev["is_free"])
        self.assertEqual(ev["price_min"], 20.0)
        self.assertEqual(ev["price_status"], "listed")

    def test_null_admission_enriched(self):
        ev = {"admission": None}
        _enrich_event(ev)
        self.assertFalse(ev["is_free"])
        self.assertIsNone(ev["price_min"])
        self.assertEqual(ev["price_status"], "unknown")

    def test_returns_same_dict(self):
        ev = {"admission": "Free"}
        result = _enrich_event(ev)
        self.assertIs(result, ev)


class TestFilterByPrice(unittest.TestCase):

    def _make_events(self):
        evs = [
            {"id": 1, "admission": "Free"},
            {"id": 2, "admission": "$5"},
            {"id": 3, "admission": "$15"},
            {"id": 4, "admission": "$10–$20"},
            {"id": 5, "admission": None},
        ]
        for ev in evs:
            _enrich_event(ev)
        return evs

    def test_any_returns_all(self):
        self.assertEqual(len(_filter_by_price(self._make_events(), "any")), 5)

    def test_none_filter_returns_all(self):
        self.assertEqual(len(_filter_by_price(self._make_events(), None)), 5)

    def test_free_filter(self):
        result = _filter_by_price(self._make_events(), "free")
        self.assertEqual(len(result), 1)
        self.assertEqual(result[0]["id"], 1)

    def test_listed_filter(self):
        result = _filter_by_price(self._make_events(), "listed")
        ids = {e["id"] for e in result}
        self.assertEqual(ids, {2, 3, 4})

    def test_unknown_filter(self):
        result = _filter_by_price(self._make_events(), "unknown")
        self.assertEqual(len(result), 1)
        self.assertEqual(result[0]["id"], 5)

    def test_max_includes_free(self):
        result = _filter_by_price(self._make_events(), "max", max_price=10.0)
        ids = {e["id"] for e in result}
        self.assertIn(1, ids)  # Free always passes

    def test_max_includes_under_threshold(self):
        result = _filter_by_price(self._make_events(), "max", max_price=10.0)
        ids = {e["id"] for e in result}
        self.assertIn(2, ids)  # $5 passes

    def test_max_excludes_over_threshold(self):
        result = _filter_by_price(self._make_events(), "max", max_price=10.0)
        ids = {e["id"] for e in result}
        self.assertNotIn(3, ids)  # $15 excluded

    def test_max_range_uses_price_min(self):
        # Range "$10–$20": price_min=10 which equals the threshold → included
        result = _filter_by_price(self._make_events(), "max", max_price=10.0)
        ids = {e["id"] for e in result}
        self.assertIn(4, ids)

    def test_max_excludes_unknown(self):
        result = _filter_by_price(self._make_events(), "max", max_price=100.0)
        ids = {e["id"] for e in result}
        self.assertNotIn(5, ids)  # unknown excluded even at very high max

    def test_under10_scenario(self):
        result = _filter_by_price(self._make_events(), "max", max_price=10.0)
        ids = {e["id"] for e in result}
        # Free ($0), $5 pass; $15, $10–$20 (min=10, passes), unknown excluded
        self.assertIn(1, ids)
        self.assertIn(2, ids)
        self.assertNotIn(3, ids)
        self.assertNotIn(5, ids)

    def test_under20_scenario(self):
        result = _filter_by_price(self._make_events(), "max", max_price=20.0)
        ids = {e["id"] for e in result}
        self.assertIn(1, ids)   # Free
        self.assertIn(2, ids)   # $5
        self.assertIn(3, ids)   # $15
        self.assertIn(4, ids)   # $10–$20 (min=10)
        self.assertNotIn(5, ids)  # unknown excluded


if __name__ == "__main__":
    unittest.main()
