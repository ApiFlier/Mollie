"""
Tests for api/migrations.py — app-level curated-data migrations.

Verifies:
  - sync_seed adds missing seed-managed categories/locations
  - sync_seed updates changed seed-managed rows
  - sync_seed does not overwrite user-modified rows
  - sync_seed soft-removes/deactivates seed-managed rows removed from the seed
  - sync_seed handles exact match backfill and updates
"""
import sys
import os
import json
import unittest
from unittest.mock import MagicMock, patch

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "api"))
import migrations as _mg

def _make_cursor(fetchone_seq):
    cur = MagicMock()
    cur.fetchone.side_effect = list(fetchone_seq)
    cur.lastrowid = 99
    cur.rowcount = 1
    return cur

def _make_conn(fetchone_seq=()):
    cur = _make_cursor(fetchone_seq)
    conn = MagicMock()
    conn.cursor.return_value = cur
    return conn, cur

class TestSeedSync(unittest.TestCase):
    def setUp(self):
        self.manifest_data = {
            "categories": [{"name": "hiking-trails", "icon": "trail", "color": "#5e9e6e", "display_order": 57}],
            "locations": [
                {
                    "seed_key": "hiking-trails_beechwood",
                    "seed_hash": "manifest_hash",
                    "name": "Beechwood", "category_name": "hiking-trails", "county": "Allegheny",
                    "address": "123 Main", "city": "PGH", "state": "PA", "zip": "15217",
                    "lat": 40.0, "lng": -80.0, "website": "https://specific-url.com",
                    "season_start_month": 3, "season_end_month": 11, "notes": "New notes"
                }
            ]
        }
        self.patcher = patch('builtins.open', unittest.mock.mock_open(read_data=json.dumps(self.manifest_data)))
        self.patcher.start()
        
        self.exists_patcher = patch('os.path.exists', return_value=True)
        self.exists_patcher.start()

    def tearDown(self):
        self.patcher.stop()
        self.exists_patcher.stop()

    def test_sync_adds_missing(self):
        conn, cur = _make_conn([
            None,  # category not found
            None,  # location not found by seed_key
            None,  # location not found by name
        ])
        _mg._sync_seed(conn, cur)
        
        sqls = [c.args[0] for c in cur.execute.call_args_list]
        self.assertTrue(any("INSERT INTO categories" in s for s in sqls))
        self.assertTrue(any("INSERT INTO locations" in s for s in sqls))

    def test_sync_exact_match_backfill_and_update(self):
        """Legacy row missing seed_key matches name/category, gets backfilled AND updated."""
        conn, cur = _make_conn([
            {"id": 9},  # category found
            None,       # location not found by seed_key
            {
                "id": 741, "name": "Beechwood", "category_id": 9,
                "seed_managed": False, "user_modified": False, 
                "seed_key": None, "seed_hash": None, "hidden": False,
                "website": "https://generic.pa.gov"
            }, # location found by name
        ])
        _mg._sync_seed(conn, cur)
        
        sqls = [c.args[0] for c in cur.execute.call_args_list]
        # Should see seed_key backfill
        self.assertTrue(any("UPDATE locations SET seed_key = %s, seed_managed = TRUE" in s for s in sqls))
        # Should see managed field update (including website)
        self.assertTrue(any("UPDATE locations SET name = %s" in s and "website = %s" in s for s in sqls))
        # Should NOT see INSERT
        self.assertFalse(any("INSERT INTO locations" in s for s in sqls))

    def test_sync_updates_stale_managed_row(self):
        """Existing seed-managed row with stale hash gets updated."""
        conn, cur = _make_conn([
            {"id": 9},  # category found
            {
                "id": 741, "name": "Beechwood", "category_id": 9,
                "seed_managed": True, "user_modified": False, 
                "seed_key": "hiking-trails_beechwood", "seed_hash": "stale_hash", 
                "hidden": False, "website": "https://generic.pa.gov"
            }, # location found by seed_key
        ])
        _mg._sync_seed(conn, cur)
        
        sqls = [c.args[0] for c in cur.execute.call_args_list]
        # Should see update including website and new hash
        self.assertTrue(any("website = %s" in s and "seed_hash = %s" in s for s in sqls))

    def test_sync_preserves_user_modified(self):
        """user_modified=TRUE row is never overwritten, and hash is not advanced."""
        conn, cur = _make_conn([
            {"id": 9},  # category found
            {
                "id": 741, "name": "Beechwood", "category_id": 9,
                "seed_managed": True, "user_modified": True, 
                "seed_key": "hiking-trails_beechwood", "seed_hash": "old_hash", 
                "hidden": False, "website": "https://mollies-custom-url.com"
            }, # location found by seed_key
        ])
        _mg._sync_seed(conn, cur)
        
        sqls = [c.args[0] for c in cur.execute.call_args_list]
        # Should NOT see any UPDATE locations SET website = %s
        update_sqls = [s for s in sqls if "UPDATE locations SET" in s and "website =" in s]
        self.assertEqual(len(update_sqls), 0)
        # Should NOT see hash update
        hash_updates = [s for s in sqls if "seed_hash =" in s]
        self.assertEqual(len(hash_updates), 0)

    def test_sync_soft_removes_missing(self):
        """Managed rows missing from manifest are hidden if not user_modified."""
        conn, cur = _make_conn([
            {"id": 9},  # category found
            {
                "id": 10, "seed_managed": True, "user_modified": False, 
                "seed_key": "hiking-trails_beechwood", "seed_hash": "manifest_hash",
                "hidden": False
            }, # location found, matches manifest exactly (no update)
        ])
        # We need a SECOND mock manifest entry or just use the existing one and a different DB state
        # Actually, processed_seed_keys will contain 'hiking-trails_beechwood'
        # The soft-hide query looks for seed_managed = TRUE AND id NOT IN (...)
        
        _mg._sync_seed(conn, cur)
        
        sqls = [c.args[0] for c in cur.execute.call_args_list]
        self.assertTrue(any("UPDATE locations SET hidden = TRUE WHERE seed_managed = TRUE AND user_modified = FALSE" in s for s in sqls))

if __name__ == "__main__":
    unittest.main()
