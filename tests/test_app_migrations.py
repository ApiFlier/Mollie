"""
Tests for api/migrations.py — app-level curated-data migrations.

Verifies:
  - sync_seed adds missing seed-managed categories/locations
  - sync_seed updates changed seed-managed rows
  - sync_seed does not overwrite user-modified rows
  - sync_seed soft-removes/deactivates seed-managed rows removed from the seed
  - sync_seed handles exact match backfill
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
                    "seed_hash": "hash123",
                    "name": "Beechwood", "category_id": 1, "county": "Allegheny",
                    "address": "123 Main", "city": "PGH", "state": "PA", "zip": "15217",
                    "lat": 40.0, "lng": -80.0, "website": "http",
                    "season_start_month": 1, "season_end_month": 12, "notes": ""
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

    def test_sync_exact_match_backfill(self):
        conn, cur = _make_conn([
            {"id": 1},  # category found
            None,  # location not found by seed_key
            {"id": 10, "seed_managed": False, "user_modified": False, "seed_hash": "old"}, # location found by name
        ])
        _mg._sync_seed(conn, cur)
        
        sqls = [c.args[0] for c in cur.execute.call_args_list]
        self.assertTrue(any("UPDATE locations SET seed_key" in s for s in sqls))
        self.assertFalse(any("INSERT INTO locations" in s for s in sqls))
        self.assertTrue(any("UPDATE locations SET" in s and "hidden = FALSE" in s for s in sqls))

    def test_sync_updates_managed(self):
        conn, cur = _make_conn([
            {"id": 1},  # category found
            {"id": 10, "seed_managed": True, "user_modified": False, "seed_hash": "old_hash"}, # location found
        ])
        _mg._sync_seed(conn, cur)
        
        sqls = [c.args[0] for c in cur.execute.call_args_list]
        self.assertTrue(any("UPDATE locations SET" in s and "hidden = FALSE" in s for s in sqls))
        self.assertFalse(any("INSERT INTO locations" in s for s in sqls))

    def test_sync_preserves_user_modified(self):
        conn, cur = _make_conn([
            {"id": 1},  # category found
            {
                "id": 10, "seed_managed": True, "user_modified": True, "notes": "my edit",
                "seed_hash": "old_hash", "category_id": 1, "county": "Allegheny",
                "address": "123 Main", "city": "PGH", "state": "PA", "zip": "15217",
                "lat": 40.0, "lng": -80.0, "website": "http", "season_start_month": 1,
                "season_end_month": 12
            }, # location found
        ])
        _mg._sync_seed(conn, cur)
        
        sqls = [c.args[0] for c in cur.execute.call_args_list]
        update_sqls = [s for s in sqls if "UPDATE locations SET" in s and "category_id =" in s]
        self.assertEqual(len(update_sqls), 0, "Should not update fully populated fields if user_modified is True")

    def test_sync_soft_removes_missing(self):
        conn, cur = _make_conn([
            {"id": 1},  # category found
            {"id": 10, "seed_managed": True, "user_modified": False, "seed_hash": "hash123"}, # location found
        ])
        cur.rowcount = 1
        _mg._sync_seed(conn, cur)
        
        sqls = [c.args[0] for c in cur.execute.call_args_list]
        self.assertTrue(any("UPDATE locations SET hidden = TRUE WHERE seed_managed = TRUE" in s for s in sqls))

if __name__ == "__main__":
    unittest.main()
