"""
Tests for HOME_LAT/HOME_LNG env-var parsing in api/events.py.
Run with:  python -m pytest tests/ -v
       or: python tests/test_env_parsing.py
"""
import importlib
import os
import sys
import unittest

# Allow importing from api/ without installing the package.
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "api"))


def _reload_events(env_overrides):
    """Reload events module with a controlled environment."""
    clean = {k: v for k, v in os.environ.items()
             if k not in ("HOME_LAT", "HOME_LNG")}
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


class TestParseFloatEnv(unittest.TestCase):

    def _helper(self, env_overrides):
        m = _reload_events(env_overrides)
        return m.HOME_LAT, m.HOME_LNG

    def test_missing_uses_defaults(self):
        lat, lng = self._helper({})
        self.assertAlmostEqual(lat, 40.487993, places=5)
        self.assertAlmostEqual(lng, -79.805208, places=5)

    def test_blank_uses_defaults(self):
        lat, lng = self._helper({"HOME_LAT": "", "HOME_LNG": ""})
        self.assertAlmostEqual(lat, 40.487993, places=5)
        self.assertAlmostEqual(lng, -79.805208, places=5)

    def test_whitespace_uses_defaults(self):
        lat, lng = self._helper({"HOME_LAT": "   ", "HOME_LNG": "\t"})
        self.assertAlmostEqual(lat, 40.487993, places=5)
        self.assertAlmostEqual(lng, -79.805208, places=5)

    def test_invalid_string_uses_defaults(self):
        lat, lng = self._helper({"HOME_LAT": "not-a-number", "HOME_LNG": "???"})
        self.assertAlmostEqual(lat, 40.487993, places=5)
        self.assertAlmostEqual(lng, -79.805208, places=5)

    def test_valid_custom_values(self):
        lat, lng = self._helper({"HOME_LAT": "51.5074", "HOME_LNG": "-0.1278"})
        self.assertAlmostEqual(lat, 51.5074)
        self.assertAlmostEqual(lng, -0.1278)

    def test_out_of_range_lat_uses_default(self):
        lat, lng = self._helper({"HOME_LAT": "999.0", "HOME_LNG": "-79.805208"})
        self.assertAlmostEqual(lat, 40.487993, places=5)
        self.assertAlmostEqual(lng, -79.805208, places=5)

    def test_out_of_range_lng_uses_default(self):
        lat, lng = self._helper({"HOME_LAT": "40.487993", "HOME_LNG": "200.0"})
        self.assertAlmostEqual(lat, 40.487993, places=5)
        self.assertAlmostEqual(lng, -79.805208, places=5)

    def test_negative_lng_valid(self):
        lat, lng = self._helper({"HOME_LAT": "34.0522", "HOME_LNG": "-118.2437"})
        self.assertAlmostEqual(lat, 34.0522)
        self.assertAlmostEqual(lng, -118.2437)


if __name__ == "__main__":
    unittest.main()
