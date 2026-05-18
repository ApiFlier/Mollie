"""
Tests for seed.sql curated content — categories and seeded locations.

Verifies:
  - hiking-trails category exists with correct color and display_order
  - butcher category exists
  - All expected hiking trail locations are present
  - All expected butcher locations are present
  - No duplicate location names within the same category
  - seed.sql contains no external_events or external_event_user_state data
  - update-seed.sh passes bash -n syntax check

Run with:  python3 -m pytest tests/test_seed_categories.py -v
"""
import re
import subprocess
import unittest
from pathlib import Path

SEED_PATH = Path(__file__).parent.parent / "api" / "data" / "seed.sql"
UPDATE_SEED_PATH = Path(__file__).parent.parent / "scripts" / "commands" / "update-seed.sh"


def _read_seed():
    return SEED_PATH.read_text(encoding="utf-8")


class TestSeedFile(unittest.TestCase):
    def test_seed_file_exists(self):
        self.assertTrue(SEED_PATH.exists(), f"seed.sql not found at {SEED_PATH}")

    def test_seed_file_not_empty(self):
        self.assertGreater(SEED_PATH.stat().st_size, 10_000)

    def test_no_external_events_data(self):
        seed = _read_seed()
        self.assertNotIn("INSERT INTO `external_events`", seed)

    def test_no_external_event_user_state_data(self):
        seed = _read_seed()
        self.assertNotIn("INSERT INTO `external_event_user_state`", seed)


class TestCategoriesInSeed(unittest.TestCase):
    def setUp(self):
        self.seed = _read_seed()

    def _find_category_insert_line(self):
        for line in self.seed.splitlines():
            if "INSERT INTO `categories`" in line:
                return line
        return None

    def test_categories_insert_present(self):
        self.assertIsNotNone(self._find_category_insert_line(),
                             "No INSERT INTO `categories` found in seed.sql")

    def test_hiking_trails_category_exists(self):
        line = self._find_category_insert_line()
        self.assertIsNotNone(line)
        self.assertIn("hiking-trails", line)

    def test_hiking_trails_color_is_soft_green(self):
        line = self._find_category_insert_line()
        self.assertIsNotNone(line)
        # Color should be #5e9e6e (soft spring green), NOT dark red/burgundy
        self.assertIn("#5e9e6e", line)

    def test_hiking_trails_not_dark_red(self):
        line = self._find_category_insert_line()
        self.assertIsNotNone(line)
        # Ensure hiking-trails entry does not accidentally use the butcher dark red
        # Extract the hiking-trails tuple region and check color
        idx = line.find("hiking-trails")
        self.assertGreater(idx, 0)
        region = line[max(0, idx - 5):idx + 60]
        self.assertNotIn("#7f1d1d", region)

    def test_butcher_category_exists(self):
        line = self._find_category_insert_line()
        self.assertIsNotNone(line)
        self.assertIn("butcher", line)

    def test_farm_category_exists(self):
        line = self._find_category_insert_line()
        self.assertIsNotNone(line)
        self.assertIn("'farm'", line)

    def test_farmers_market_category_exists(self):
        line = self._find_category_insert_line()
        self.assertIsNotNone(line)
        self.assertIn("farmers-market", line)


class TestHikingTrailsInSeed(unittest.TestCase):
    def setUp(self):
        self.seed = _read_seed()

    def test_beechwood_farms_present(self):
        self.assertIn("Beechwood Farms Nature Reserve", self.seed)

    def test_boyce_park_present(self):
        self.assertIn("Boyce Park", self.seed)

    def test_hartwood_acres_present(self):
        self.assertIn("Hartwood Acres Park", self.seed)

    def test_harrison_hills_present(self):
        self.assertIn("Harrison Hills Park", self.seed)

    def test_three_rivers_heritage_trail_present(self):
        self.assertIn("Three Rivers Heritage Trail", self.seed)

    def test_beechwood_farms_address(self):
        self.assertIn("614 Dorseyville", self.seed)

    def test_boyce_park_address(self):
        self.assertIn("675 Old Frankstown", self.seed)

    def test_hartwood_acres_address(self):
        self.assertIn("200 Hartwood Acres", self.seed)

    def test_hiking_websites_present(self):
        self.assertIn("aswp.org", self.seed)
        self.assertIn("alleghenycounty.us", self.seed)
        self.assertIn("friendsoftheriverfront.org", self.seed)


class TestButcherLocationsInSeed(unittest.TestCase):
    def setUp(self):
        self.seed = _read_seed()

    def test_strip_district_meats_present(self):
        self.assertIn("Strip District Meats", self.seed)

    def test_fat_butcher_present(self):
        self.assertIn("Fat Butcher", self.seed)

    def test_weiss_meats_present(self):
        self.assertIn("Weiss Meats", self.seed)

    def test_strip_district_address(self):
        self.assertIn("2121 Penn Avenue", self.seed)

    def test_fat_butcher_address(self):
        self.assertIn("5151 Butler", self.seed)

    def test_weiss_meats_address(self):
        self.assertIn("100 Terence", self.seed)



class TestNoDuplicateLocationNames(unittest.TestCase):
    """Verify no location name appears twice in the locations INSERT block."""

    def _extract_location_names(self):
        seed = _read_seed()
        names = []
        # Match the name field (first string value after the id and category_id integers)
        # locations INSERT has: (id,'name',category_id,...)
        for match in re.finditer(r"\(\d+,'([^']+)',\d+,", seed):
            names.append(match.group(1))
        return names

    def test_no_duplicate_location_names(self):
        names = self._extract_location_names()
        seen = set()
        dupes = []
        for name in names:
            if name in seen:
                dupes.append(name)
            seen.add(name)
        self.assertEqual(dupes, [], f"Duplicate location names in seed: {dupes}")


class TestUpdateSeedScript(unittest.TestCase):
    def test_update_seed_sh_bash_syntax(self):
        result = subprocess.run(
            ["bash", "-n", str(UPDATE_SEED_PATH)],
            capture_output=True, text=True
        )
        self.assertEqual(result.returncode, 0,
                         f"bash -n failed:\n{result.stderr}")

    def test_update_seed_excludes_external_events_comment(self):
        content = UPDATE_SEED_PATH.read_text(encoding="utf-8")
        self.assertIn("external_events", content)

    def test_update_seed_has_yes_flag_support(self):
        content = UPDATE_SEED_PATH.read_text(encoding="utf-8")
        self.assertIn("--yes", content)


if __name__ == "__main__":
    unittest.main()
