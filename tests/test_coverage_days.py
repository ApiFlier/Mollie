"""
Tests for coverage_days validation / clamping logic in events.py.
Run with:  python3 -m pytest tests/ -v
"""
import sys
import os
import unittest

# Load events.py directly (no DB needed — module-level code is pure Python).
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "api"))
import events as _ev


class TestClampCoverageDays(unittest.TestCase):
    """Unit tests for events._clamp_coverage_days."""

    def test_default_60(self):
        self.assertEqual(_ev._clamp_coverage_days(None), 60)

    def test_blank_string_fallback(self):
        self.assertEqual(_ev._clamp_coverage_days(""), 60)

    def test_non_numeric_fallback(self):
        self.assertEqual(_ev._clamp_coverage_days("abc"), 60)

    def test_float_string_converts(self):
        # int("45.0") raises, so floats-as-strings fall back to default
        self.assertEqual(_ev._clamp_coverage_days("45.0"), 60)

    def test_valid_30(self):
        self.assertEqual(_ev._clamp_coverage_days(30), 30)

    def test_valid_45(self):
        self.assertEqual(_ev._clamp_coverage_days(45), 45)

    def test_valid_7_min_boundary(self):
        self.assertEqual(_ev._clamp_coverage_days(7), 7)

    def test_valid_180_max_boundary(self):
        self.assertEqual(_ev._clamp_coverage_days(180), 180)

    def test_below_min_clamps_to_7(self):
        self.assertEqual(_ev._clamp_coverage_days(3), 7)

    def test_zero_clamps_to_7(self):
        self.assertEqual(_ev._clamp_coverage_days(0), 7)

    def test_negative_clamps_to_7(self):
        self.assertEqual(_ev._clamp_coverage_days(-10), 7)

    def test_above_max_clamps_to_180(self):
        self.assertEqual(_ev._clamp_coverage_days(250), 180)

    def test_string_integer_works(self):
        self.assertEqual(_ev._clamp_coverage_days("60"), 60)

    def test_string_below_min_clamps(self):
        self.assertEqual(_ev._clamp_coverage_days("2"), 7)

    def test_string_above_max_clamps(self):
        self.assertEqual(_ev._clamp_coverage_days("999"), 180)

    def test_integer_int(self):
        self.assertEqual(_ev._clamp_coverage_days(90), 90)

    def test_custom_default(self):
        self.assertEqual(_ev._clamp_coverage_days(None, default=45), 45)


if __name__ == "__main__":
    unittest.main()
