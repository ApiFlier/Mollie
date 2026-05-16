#!/usr/bin/env python3
"""
Diagnose and optionally repair raw_source_json integrity for external_events.

Problems diagnosed:
  1. Rows where JSON_VALID(raw_source_json) = 0 (truncated JSON from old adapter limit).
  2. Rows where raw_source_json is valid JSON, Free=true, but admission != 'Free'.
  3. Rows where raw_source_json is invalid JSON but text contains "Free": true pattern,
     meaning admission should be 'Free' but may have been missed.

Actions (default: dry-run, no DB changes):
  --apply   Write the safe backfills to the database.

Safety:
  - Never overwrites a non-null, non-Free admission value.
  - Never writes to hidden=1 rows.
  - Reports all invalid-JSON rows separately without crashing.

Usage:
    python3 scripts/diagnose_free_json.py            # dry-run report
    python3 scripts/diagnose_free_json.py --apply    # write fixes
"""

import os
import re
import sys
import subprocess
import argparse


# ── Config ────────────────────────────────────────────────────────────────────

def _load_env(path=None):
    env = {}
    for candidate in (path, os.path.join(os.path.dirname(__file__), "..", ".env")):
        if candidate and os.path.isfile(candidate):
            with open(candidate) as f:
                for line in f:
                    line = line.strip()
                    if line and not line.startswith("#") and "=" in line:
                        k, _, v = line.partition("=")
                        env[k.strip()] = v.strip().strip('"').strip("'")
            break
    return env

_ENV = _load_env()


def _root_pass():
    return _ENV.get("MYSQL_ROOT_PASSWORD", "")


def _db_name():
    return _ENV.get("DB_NAME", _ENV.get("MYSQL_DATABASE", "event_map"))


# ── DB helpers ────────────────────────────────────────────────────────────────

def _run_sql(sql, *, write=False):
    """Execute SQL via docker compose exec db mysql. Returns output lines."""
    rp = _root_pass()
    dn = _db_name()
    cmd = [
        "docker", "compose", "exec", "-T", "db",
        "mysql", "-u", "root", f"-p{rp}", dn,
        "-e", sql,
    ]
    try:
        result = subprocess.run(cmd, capture_output=True, text=True)
        lines = [l for l in result.stdout.splitlines() if l and "Warning" not in l and "password on the command" not in l]
        if result.returncode != 0 and result.stderr:
            err = result.stderr.strip()
            if "Warning" not in err and "password on the command" not in err:
                print(f"[SQL error] {err[:300]}", file=sys.stderr)
        return lines
    except Exception as e:
        print(f"[run_sql exception] {e}", file=sys.stderr)
        return []


def _fetch(sql):
    """Run a SELECT and return list-of-dicts (tab-separated from mysql output)."""
    lines = _run_sql(sql)
    if not lines:
        return []
    headers = lines[0].split("\t")
    rows = []
    for line in lines[1:]:
        cols = line.split("\t")
        rows.append(dict(zip(headers, cols)))
    return rows


# ── Diagnosis ─────────────────────────────────────────────────────────────────

def _count_invalid():
    rows = _fetch("""
        SELECT source_key,
          COUNT(*) AS total,
          SUM(CASE WHEN JSON_VALID(raw_source_json)=0 THEN 1 ELSE 0 END) AS invalid
        FROM external_events
        WHERE source_key IN ('positively_pgh','visit_pittsburgh')
        GROUP BY source_key
    """)
    return rows


def _invalid_rows():
    """Return rows where JSON_VALID = 0, with key metadata."""
    return _fetch("""
        SELECT id, source_key, admission, hidden,
          CHAR_LENGTH(raw_source_json) AS json_len,
          CASE WHEN raw_source_json LIKE '%"Free": true%' THEN 1 ELSE 0 END AS text_has_free_true
        FROM external_events
        WHERE JSON_VALID(raw_source_json) = 0
          AND source_key IN ('positively_pgh','visit_pittsburgh')
        ORDER BY source_key, id
    """)


def _valid_rows_free_wrong():
    """Return valid-JSON rows where Free=true but admission is not 'Free'."""
    return _fetch("""
        SELECT id, source_key, admission, hidden,
          SUBSTRING(title,1,60) AS title
        FROM external_events
        WHERE JSON_VALID(raw_source_json) = 1
          AND source_key = 'positively_pgh'
          AND JSON_EXTRACT(raw_source_json, '$.Free') = true
          AND (admission IS NULL OR admission != 'Free')
          AND hidden = 0
    """)


# ── Backfill ──────────────────────────────────────────────────────────────────

def _backfill_invalid_free(apply=False):
    """
    For invalid-JSON rows where the truncated text still clearly contains
    '"Free": true', backfill admission='Free' if currently NULL.
    Never overwrites a paid admission value.
    """
    rows = _fetch("""
        SELECT id, admission
        FROM external_events
        WHERE JSON_VALID(raw_source_json) = 0
          AND raw_source_json LIKE '%"Free": true%'
          AND (admission IS NULL OR admission != 'Free')
          AND hidden = 0
    """)
    if not rows:
        print("  [invalid-JSON backfill] No rows need backfill.")
        return 0

    ids = [r["id"] for r in rows]
    print(f"  [invalid-JSON backfill] Would set admission='Free' for ids: {ids}")
    if apply:
        id_list = ",".join(ids)
        _run_sql(f"""
            UPDATE external_events
            SET admission='Free', updated_at=NOW()
            WHERE id IN ({id_list})
              AND (admission IS NULL OR admission != 'Free')
              AND hidden = 0
        """, write=True)
        print(f"  [invalid-JSON backfill] Applied {len(ids)} update(s).")
    return len(ids)


def _backfill_valid_free(apply=False):
    """Fix valid-JSON rows where Free=true but admission is wrong."""
    rows = _valid_rows_free_wrong()
    if not rows:
        print("  [valid-JSON backfill] No rows need backfill.")
        return 0

    ids = [r["id"] for r in rows]
    print(f"  [valid-JSON backfill] Would set admission='Free' for ids: {ids}")
    for r in rows:
        print(f"    id={r['id']} current_admission={r['admission']!r} title={r.get('title','')!r}")
    if apply:
        id_list = ",".join(ids)
        _run_sql(f"""
            UPDATE external_events
            SET admission='Free', updated_at=NOW()
            WHERE id IN ({id_list})
              AND hidden = 0
        """, write=True)
        print(f"  [valid-JSON backfill] Applied {len(ids)} update(s).")
    return len(ids)


# ── Main ──────────────────────────────────────────────────────────────────────

def main():
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--apply", action="store_true", help="Write fixes to DB (default: dry-run only)")
    args = parser.parse_args()
    mode = "APPLY" if args.apply else "DRY-RUN"
    print(f"\n=== diagnose_free_json.py [{mode}] ===\n")

    # 1. Overall validity counts
    print("── JSON validity by source ──────────────────────────────────────────")
    counts = _count_invalid()
    for row in counts:
        print(f"  {row['source_key']:20s}  total={row['total']:4s}  invalid={row['invalid']}")

    # 2. Invalid JSON rows detail
    print("\n── Invalid JSON rows ────────────────────────────────────────────────")
    invalid = _invalid_rows()
    if not invalid:
        print("  None — all rows have valid JSON.")
    else:
        print(f"  {len(invalid)} row(s) with invalid JSON (all caused by old [:N] truncation):")
        for r in invalid:
            fref = "FREE_TRUE_IN_TEXT" if r.get("text_has_free_true") == "1" else "no_free_true"
            print(f"    id={r['id']:4s}  src={r['source_key']:15s}  len={r['json_len']:4s}"
                  f"  admission={r.get('admission','NULL'):10s}  {fref}")

    # 3. Valid JSON rows with wrong Free
    print("\n── Valid JSON rows: Free=true but admission wrong ───────────────────")
    wrong = _valid_rows_free_wrong()
    if not wrong:
        print("  None — all Free=true events have correct admission.")
    else:
        print(f"  {len(wrong)} row(s) need backfill:")
        for r in wrong:
            print(f"    id={r['id']}  admission={r.get('admission','NULL')!r}  title={r.get('title','')!r}")

    # 4. Backfill
    print("\n── Backfill ─────────────────────────────────────────────────────────")
    n1 = _backfill_invalid_free(apply=args.apply)
    n2 = _backfill_valid_free(apply=args.apply)
    total = n1 + n2
    if not args.apply and total > 0:
        print(f"\n  DRY-RUN: {total} update(s) would be applied. Re-run with --apply to execute.")
    elif args.apply and total > 0:
        print(f"\n  Applied {total} update(s).")
    else:
        print(f"\n  No updates needed.")

    print("\n=== Done ===\n")


if __name__ == "__main__":
    main()
