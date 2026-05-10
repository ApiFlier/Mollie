#!/usr/bin/env python3
"""
Event Map - Duplicate Location Report & Deduplication Tool

Identifies likely duplicate records using normalized combinations of:
  category, name, city, county, address

Usage:
    python3 scripts/find-duplicates.py           # Report only
    python3 scripts/find-duplicates.py --dedupe  # Dry-run deduplication
    python3 scripts/find-duplicates.py --apply   # Execute deduplication (CAUTION)

Requires:
    - Docker container event-map-db running
    - mysql client available (via Docker exec)
    - .env file present in repo root
"""

import os
import re
import sys
import subprocess
import argparse
from collections import defaultdict

# ---------------------------------------------------------------------------
# Connection helpers
# ---------------------------------------------------------------------------

def _load_env(env_file):
    env = {}
    try:
        if os.path.exists(env_file):
            with open(env_file) as f:
                for line in f:
                    line = line.strip()
                    if line and not line.startswith("#") and "=" in line:
                        k, v = line.split("=", 1)
                        env[k.strip()] = v.strip()
    except Exception:
        pass
    return env

def _get_db_creds():
    script_dir = os.path.dirname(os.path.abspath(__file__))
    repo_root = os.path.dirname(script_dir)
    env_file = os.path.join(repo_root, ".env")
    env = _load_env(env_file)

    creds = {
        "db_host": os.environ.get("DB_HOST", env.get("DB_HOST", "")),
        "db_name": os.environ.get("DB_NAME", env.get("DB_NAME", "event_map")),
        "db_user": os.environ.get("DB_USER", env.get("DB_USER", "")),
        "db_pass": os.environ.get("DB_PASSWORD", env.get("DB_PASSWORD", "")),
        "root_pass": env.get("MYSQL_ROOT_PASSWORD", "")
    }
    return creds

def _run_query(sql, fetch=True):
    """Run a SQL query via Docker or local mysql client."""
    creds = _get_db_creds()
    db_name = creds["db_name"]
    root_pass = creds["root_pass"]
    db_host = creds["db_host"]
    db_user = creds["db_user"]
    db_pass = creds["db_pass"]

    # Try via Docker exec (most common deployment)
    if root_pass:
        try:
            cmd = ["docker", "exec", "event-map-db",
                   "mysql", "-uroot", f"-p{root_pass}", db_name,
                   "-e", sql, "--batch"]
            if fetch:
                cmd.append("--skip-column-names")
            
            result = subprocess.run(cmd, capture_output=True, text=True, timeout=30)
            if result.returncode == 0:
                return result.stdout if fetch else True
        except (subprocess.TimeoutExpired, FileNotFoundError):
            pass

    # Try direct connection via mysql client
    if db_host and db_user:
        try:
            cmd = ["mysql", f"-h{db_host}", f"-u{db_user}", f"-p{db_pass}",
                   db_name, "-e", sql, "--batch"]
            if fetch:
                cmd.append("--skip-column-names")
            
            result = subprocess.run(cmd, capture_output=True, text=True, timeout=30)
            if result.returncode == 0:
                return result.stdout if fetch else True
        except (subprocess.TimeoutExpired, FileNotFoundError):
            pass

    if not fetch:
        return False
    
    print("ERROR: Could not connect to the database.", file=sys.stderr)
    sys.exit(1)

def _fetch_locations():
    """Fetch all locations and child record counts."""
    sql = """
        SELECT l.id, l.name, l.address, l.city, l.state, l.county, l.lat, l.lng,
               c.name AS category,
               (SELECT COUNT(*) FROM crops WHERE location_id = l.id) as crop_count,
               (SELECT COUNT(*) FROM notes WHERE location_id = l.id) as note_count
        FROM locations l
        LEFT JOIN categories c ON l.category_id = c.id
        ORDER BY l.id
    """
    stdout = _run_query(sql)
    return _parse_locations_tsv(stdout)

def _parse_locations_tsv(text):
    cols = ["id", "name", "address", "city", "state", "county", "lat", "lng", "category", "crop_count", "note_count"]
    rows = []
    for line in text.splitlines():
        if not line.strip():
            continue
        parts = line.split("\t")
        row = {}
        for i, col in enumerate(cols):
            val = parts[i] if i < len(parts) else ""
            if col in ["id", "crop_count", "note_count"]:
                row[col] = int(val) if val and val != "NULL" else 0
            else:
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

        # Secondary key: category + normalized name + county
        if name_key and county_key:
            k2 = ("by_county", cat, name_key, county_key)
            groups[k2].append(loc)

        # Tertiary key: category + address
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
# Deduplication & Merging
# ---------------------------------------------------------------------------

def _deduplicate(duplicate_groups, apply=False):
    """Identify or execute deduplication steps."""
    if not duplicate_groups:
        print("No duplicates to process.")
        return

    print(f"\n{'[DRY RUN] ' if not apply else '[APPLYING] '}Processing {len(duplicate_groups)} groups...\n")

    total_deleted = 0
    total_crops_moved = 0
    total_notes_moved = 0

    for i, (key, members) in enumerate(duplicate_groups, 1):
        members = sorted(members, key=lambda x: x["id"])
        keep = members[0]
        remove = members[1:]
        
        keep_id = keep["id"]
        remove_ids = [r["id"] for r in remove]
        
        print(f"Group {i}: Keeping ID {keep_id}, removing {', '.join(map(str, remove_ids))}")
        
        for r in remove:
            r_id = r["id"]
            total_deleted += 1
            
            if r["crop_count"] > 0:
                print(f"  - Moving {r['crop_count']} crops from {r_id} to {keep_id}")
                if apply:
                    _run_query(f"UPDATE crops SET location_id = {keep_id} WHERE location_id = {r_id}", fetch=False)
                total_crops_moved += r["crop_count"]
            
            if r["note_count"] > 0:
                print(f"  - Moving {r['note_count']} notes from {r_id} to {keep_id}")
                if apply:
                    _run_query(f"UPDATE notes SET location_id = {keep_id} WHERE location_id = {r_id}", fetch=False)
                total_notes_moved += r["note_count"]
            
            if apply:
                _run_query(f"DELETE FROM locations WHERE id = {r_id}", fetch=False)

        # Post-merge crop deduplication for this location
        if apply:
            # Delete duplicate crops for the 'keep' location (same normalized name)
            _run_query(f"""
                DELETE c1 FROM crops c1
                INNER JOIN crops c2 ON c1.location_id = c2.location_id
                AND LOWER(TRIM(c1.name)) = LOWER(TRIM(c2.name))
                WHERE c1.location_id = {keep_id} AND c1.id > c2.id
            """, fetch=False)

    print("-" * 72)
    print(f"Summary of {'planned ' if not apply else ''}actions:")
    print(f"  Locations to delete: {total_deleted}")
    print(f"  Crops to re-parent:  {total_crops_moved}")
    print(f"  Notes to re-parent:  {total_notes_moved}")
    if not apply:
        print("\n  This was a DRY RUN. No changes were made to the database.")
        print("  Use --apply to execute these changes.")
    else:
        print("\n  Deduplication complete.")
    print("-" * 72)

# ---------------------------------------------------------------------------
# Report rendering
# ---------------------------------------------------------------------------

def _render_report(locations, duplicate_groups):
    total = len(locations)
    dupe_count = sum(len(g) for _, g in duplicate_groups)

    print("=" * 72)
    print("  Event Map — Duplicate Location Report")
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
            cc   = loc.get("crop_count") or 0
            nc   = loc.get("note_count") or 0
            
            child_str = f" [{cc} crops, {nc} notes]" if cc or nc else ""
            loc_str = ", ".join(filter(None, [city, county]))
            print(f"  ID {loc.get('id'):>5}  [{cat}]  {name}{child_str}")
            if addr or loc_str:
                print(f"           loc:  {addr or '(no addr)'}, {loc_str or '(no city/county)'}")
        print()

    print("=" * 72)
    print("  To investigate a record:")
    print("    http://localhost:<PORT>/admin/edit.html?id=<ID>")
    print()
    print("  Use --dedupe for a dry-run cleanup plan.")
    print("=" * 72)
    print()

# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def main():
    parser = argparse.ArgumentParser(description="Event Map Duplicate Management")
    parser.add_argument("--dedupe", action="store_true", help="Show deduplication plan (dry-run)")
    parser.add_argument("--apply", action="store_true", help="Execute deduplication (modifies database)")
    args = parser.parse_args()

    locations = _fetch_locations()
    duplicate_groups = _find_duplicates(locations)

    if args.apply:
        print("WARNING: This will MODIFY the database.")
        print("Have you run scripts/backup-db.sh recently?")
        confirm = input("Type 'yes' to continue: ")
        if confirm.lower() == 'yes':
            _deduplicate(duplicate_groups, apply=True)
        else:
            print("Aborted.")
    elif args.dedupe:
        _deduplicate(duplicate_groups, apply=False)
    else:
        _render_report(locations, duplicate_groups)

if __name__ == "__main__":
    main()
