#!/usr/bin/env python3
"""
Event Map - Duplicate Location Report

Identifies likely duplicate records using normalized combinations of:
  category, name, city, county, address

This script is READ-ONLY. It never modifies the database.

Usage:
    python3 scripts/find-duplicates.py

Requires:
    - Docker container event-map-db running
    - mysql client available (via Docker exec)
    - .env file present in repo root

Or, if running against a live database directly, set env vars:
    DB_HOST, DB_PORT, DB_NAME, DB_USER, DB_PASSWORD
"""

import os
import re
import sys
import subprocess
import json
from collections import defaultdict

# ---------------------------------------------------------------------------
# Connection helpers
# ---------------------------------------------------------------------------

def _load_env(env_file):
    env = {}
    try:
        with open(env_file) as f:
            for line in f:
                line = line.strip()
                if line and not line.startswith("#") and "=" in line:
                    k, v = line.split("=", 1)
                    env[k.strip()] = v.strip()
    except FileNotFoundError:
        pass
    return env

def _fetch_locations():
    """Fetch all locations from the database. Returns list of dicts."""
    script_dir = os.path.dirname(os.path.abspath(__file__))
    repo_root = os.path.dirname(script_dir)
    env_file = os.path.join(repo_root, ".env")
    env = _load_env(env_file)

    # Try environment variables first, then .env file
    db_host = os.environ.get("DB_HOST", env.get("DB_HOST", ""))
    db_name = os.environ.get("DB_NAME", env.get("DB_NAME", "event_map"))
    db_user = os.environ.get("DB_USER", env.get("DB_USER", ""))
    db_pass = os.environ.get("DB_PASSWORD", env.get("DB_PASSWORD", ""))
    root_pass = env.get("MYSQL_ROOT_PASSWORD", "")

    sql = """
        SELECT l.id, l.name, l.address, l.city, l.state, l.county, l.lat, l.lng,
               c.name AS category
        FROM locations l
        LEFT JOIN categories c ON l.category_id = c.id
        ORDER BY l.id
    """

    # Try via Docker exec (most common deployment)
    if root_pass:
        try:
            result = subprocess.run(
                ["docker", "exec", "event-map-db",
                 "mysql", "-uroot", f"-p{root_pass}", db_name,
                 "-e", sql, "--batch", "--skip-column-names"],
                capture_output=True, text=True, timeout=15
            )
            if result.returncode == 0:
                return _parse_mysql_tsv(result.stdout)
        except (subprocess.TimeoutExpired, FileNotFoundError):
            pass

    # Try direct connection via mysql client
    if db_host and db_user:
        try:
            result = subprocess.run(
                ["mysql", f"-h{db_host}", f"-u{db_user}", f"-p{db_pass}",
                 db_name, "-e", sql, "--batch", "--skip-column-names"],
                capture_output=True, text=True, timeout=15
            )
            if result.returncode == 0:
                return _parse_mysql_tsv(result.stdout)
        except (subprocess.TimeoutExpired, FileNotFoundError):
            pass

    print("ERROR: Could not connect to the database.", file=sys.stderr)
    print("  Make sure event-map-db container is running, or set DB_HOST/DB_USER/DB_PASSWORD.", file=sys.stderr)
    sys.exit(1)

def _parse_mysql_tsv(text):
    cols = ["id", "name", "address", "city", "state", "county", "lat", "lng", "category"]
    rows = []
    for line in text.splitlines():
        if not line.strip():
            continue
        parts = line.split("\t")
        row = {}
        for i, col in enumerate(cols):
            val = parts[i] if i < len(parts) else ""
            row[col] = None if val == "NULL" else val
        rows.append(row)
    return rows

# ---------------------------------------------------------------------------
# Normalization helpers
# ---------------------------------------------------------------------------

def _norm(s):
    """Normalize a string: lowercase, collapse whitespace, strip punctuation."""
    if not s:
        return ""
    s = s.lower().strip()
    s = re.sub(r"[^\w\s]", " ", s)   # remove punctuation
    s = re.sub(r"\s+", " ", s).strip()
    return s

def _norm_name(name):
    """Normalize a place name, removing common suffixes."""
    s = _norm(name)
    for suffix in ["farm", "farms", "orchard", "orchards", "market", "markets",
                   "nursery", "festival", "fair", "llc", "inc", "co"]:
        s = re.sub(r"\b" + suffix + r"\b", "", s)
    return re.sub(r"\s+", " ", s).strip()

# ---------------------------------------------------------------------------
# Duplicate detection
# ---------------------------------------------------------------------------

def _find_duplicates(locations):
    """Return groups of likely duplicate records."""
    # Build keys: (category, norm_name, norm_city_or_county)
    # Also check near-identical normalized names in the same category regardless of city.
    groups = defaultdict(list)

    for loc in locations:
        cat = (loc.get("category") or "").lower()
        name_key = _norm_name(loc.get("name") or "")
        city_key = _norm(loc.get("city") or "")
        county_key = _norm(loc.get("county") or "")
        addr_key = _norm(loc.get("address") or "")

        # Primary key: category + normalized name + city
        if name_key:
            k1 = (cat, name_key, city_key)
            groups[k1].append(loc)

        # Secondary key: category + normalized name + county (catches city spelling variants)
        if name_key and county_key:
            k2 = ("by_county", cat, name_key, county_key)
            groups[k2].append(loc)

        # Tertiary key: category + address (catches renamed locations at same address)
        if addr_key and city_key:
            k3 = ("by_addr", cat, addr_key, city_key)
            groups[k3].append(loc)

    seen_pairs = set()
    duplicate_groups = []

    for key, members in groups.items():
        if len(members) < 2:
            continue
        ids = tuple(sorted(m["id"] for m in members))
        if ids in seen_pairs:
            continue
        seen_pairs.add(ids)
        duplicate_groups.append((key, members))

    return duplicate_groups

# ---------------------------------------------------------------------------
# Report rendering
# ---------------------------------------------------------------------------

def _render_report(locations, duplicate_groups):
    total = len(locations)
    dupe_count = sum(len(g) for _, g in duplicate_groups)

    print("=" * 72)
    print("  Event Map — Duplicate Location Report")
    print("  READ-ONLY: this script makes no changes to the database.")
    print("=" * 72)
    print(f"\n  Total locations scanned: {total}")
    print(f"  Likely duplicate groups: {len(duplicate_groups)}")
    print(f"  Records in those groups: {dupe_count}")

    if not duplicate_groups:
        print("\n  No likely duplicates found.\n")
        return

    print()
    for i, (key, members) in enumerate(duplicate_groups, 1):
        key_type = key[0] if isinstance(key[0], str) and key[0].startswith("by_") else "name+city"
        if key_type == "by_county":
            match_basis = "name + county"
        elif key_type == "by_addr":
            match_basis = "address"
        else:
            match_basis = "name + city"

        print(f"--- Group {i}  (matched on: {match_basis}) " + "-" * max(0, 48 - len(str(i))))
        for loc in sorted(members, key=lambda x: int(x["id"])):
            name = loc.get("name") or "(no name)"
            cat  = loc.get("category") or "?"
            city = loc.get("city") or ""
            county = loc.get("county") or ""
            addr = loc.get("address") or ""
            lat  = loc.get("lat") or ""
            lng  = loc.get("lng") or ""
            loc_str = ", ".join(filter(None, [city, county]))
            coord_str = f"({lat}, {lng})" if lat and lng else "(no coords)"
            print(f"  ID {loc.get('id'):>5}  [{cat}]  {name}")
            if addr:
                print(f"           addr: {addr}")
            print(f"           loc:  {loc_str or '(none)'}  {coord_str}")
        print()

    print("=" * 72)
    print("  To investigate a record:")
    print("    http://localhost:<PORT>/admin/edit.html?id=<ID>")
    print()
    print("  DO NOT run DELETE queries without verifying each record first.")
    print("=" * 72)
    print()

# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    locations = _fetch_locations()
    duplicate_groups = _find_duplicates(locations)
    _render_report(locations, duplicate_groups)
