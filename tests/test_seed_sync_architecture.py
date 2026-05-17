"""
Tests for Seed Sync Architecture and URL quality.
"""
import sys
import os
import json
import unittest

# Allow direct import of api/ modules
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "api"))

class TestSeedManifest(unittest.TestCase):
    def setUp(self):
        self.manifest_path = os.path.join(os.path.dirname(__file__), "..", "api", "data", "seed_manifest.json")
        self.assertTrue(os.path.exists(self.manifest_path), "seed_manifest.json must exist")
        with open(self.manifest_path) as f:
            self.manifest = json.load(f)

    def test_manifest_structure(self):
        self.assertIn("categories", self.manifest)
        self.assertIn("locations", self.manifest)
        self.assertTrue(len(self.manifest["locations"]) >= 49, "Expect at least 37 trails + 12 butchers")

    def test_hiking_trails_count(self):
        trails = [l for l in self.manifest["locations"] if l.get("category_name") == "hiking-trails"]
        self.assertTrue(len(trails) >= 37, f"Expect at least 37 hiking trails, found {len(trails)}")

    def test_butchers_count(self):
        butchers = [l for l in self.manifest["locations"] if l.get("category_name") == "butcher"]
        self.assertTrue(len(butchers) >= 12, f"Expect at least 12 butchers, found {len(butchers)}")

    def test_specific_urls(self):
        """Ensure no hiking trails point to the generic DCNR homepage."""
        bad_urls = {
            "https://www.dcnr.pa.gov",
            "http://www.dcnr.pa.gov",
            "https://www.pa.gov/agencies/dcnr",
            "https://www.pa.gov/agencies/dcnr/recreation/where-to-go/state-parks",
            "https://www.pa.gov/agencies/dcnr/recreation/where-to-go/state-forests"
        }
        for loc in self.manifest["locations"]:
            if loc.get("category_name") == "hiking-trails":
                url = loc.get("website")
                self.assertNotIn(url, bad_urls, f"Location {loc['name']} has generic URL: {url}")
                if "pa.gov" in str(url) and "dcnr" in str(url):
                    self.assertTrue("find-a-park" in url or "find-a-forest" in url or "what-to-do" in url, 
                                    f"Location {loc['name']} has non-specific DCNR URL: {url}")

    def test_major_parks_have_specific_urls(self):
        expected_specifics = {
            "Raccoon Creek State Park": "raccoon-creek-state-park",
            "Moraine State Park": "moraine-state-park",
            "McConnells Mill State Park": "mcconnells-mill-state-park",
            "Ohiopyle State Park": "ohiopyle-state-park",
            "Oil Creek State Park": "oil-creek-state-park",
            "Keystone State Park": "keystone-state-park",
            "Laurel Hill State Park": "laurel-hill-state-park",
            "Cook Forest State Park": "cook-forest-state-park",
            "Jennings Environmental Education Center": "jennings-environmental-education-center"
        }
        loc_map = {l["name"]: l for l in self.manifest["locations"]}
        for name, slug in expected_specifics.items():
            self.assertIn(name, loc_map)
            url = loc_map[name].get("website")
            self.assertIn(slug, url, f"URL for {name} should contain {slug}: {url}")


class TestSeedSqlBaseline(unittest.TestCase):
    def setUp(self):
        self.seed_path = os.path.join(os.path.dirname(__file__), "..", "api", "data", "seed.sql")
        self.assertTrue(os.path.exists(self.seed_path), "seed.sql must exist")
        with open(self.seed_path) as f:
            self.seed_content = f.read()

    def test_no_external_events_data(self):
        self.assertNotIn("INSERT INTO `external_events`", self.seed_content)

    def test_contains_curated_data(self):
        self.assertIn("INSERT INTO `locations`", self.seed_content)
        self.assertIn("Moraine State Park", self.seed_content)
        self.assertIn("Strip District Meats", self.seed_content)

    def test_contains_seed_sync_columns(self):
        self.assertIn("`seed_key`", self.seed_content)
        self.assertIn("`seed_hash`", self.seed_content)
        self.assertIn("`seed_managed`", self.seed_content)


if __name__ == "__main__":
    unittest.main()
