#!/usr/bin/env python3
"""
Improve geocoding accuracy using the US Census geocoder.

The Census geocoder is free, requires no API key, and uses TIGER data 
which is generally more accurate for rural US addresses than OSM/Nominatim.

If Census finds a match, we use it. Otherwise we keep the existing 
(usually Nominatim) result. A sanity check rejects matches that land 
more than 35 miles from the previous position (likely wrong city).
"""

import json
import sys
import time
from pathlib import Path
import requests

DATA_DIR = Path(__file__).resolve().parent.parent / "data"
FILE = DATA_DIR / "mollies_guide_geocoded.json"

CENSUS_URL = "https://geocoding.geo.census.gov/geocoder/locations/onelineaddress"
RATE_LIMIT_SECONDS = 0.5
MAX_REASONABLE_DEGREES = 0.5  # ~35 miles, anything more is suspect


def census_lookup(address, city, state, zip_code):
    """Returns (lat, lng) on a successful match, otherwise (None, None)."""
    full = f"{address}, {city}, {state} {zip_code}".strip(", ")
    try:
        r = requests.get(
            CENSUS_URL,
            params={
                "address": full,
                "benchmark": "Public_AR_Current",
                "format": "json",
            },
            timeout=15,
        )
        r.raise_for_status()
        matches = r.json().get("result", {}).get("addressMatches", [])
        if matches:
            coords = matches[0].get("coordinates", {})
            lat, lng = coords.get("y"), coords.get("x")
            if lat is not None and lng is not None:
                return float(lat), float(lng)
    except requests.RequestException as e:
        print(f"    request error: {e}", file=sys.stderr)
    return None, None


def main():
    if not FILE.exists():
        print(f"ERROR: {FILE} not found. Run geocode.py first.", file=sys.stderr)
        sys.exit(1)

    with open(FILE) as f:
        data = json.load(f)

    locations = data["locations"]
    total = len(locations)
    improved = 0
    no_change = 0
    rejected_sanity = 0
    no_match = 0

    print(f"Trying US Census geocoder on {total} locations...\n")

    for i, loc in enumerate(locations, 1):
        name = loc.get("name", "(unnamed)")
        addr = loc.get("address", "")
        if not addr:
            print(f"[{i}/{total}] {name}: SKIP (no address)")
            continue

        old_lat = loc.get("lat")
        old_lng = loc.get("lng")

        new_lat, new_lng = census_lookup(
            addr,
            loc.get("city", ""),
            loc.get("state", ""),
            loc.get("zip", ""),
        )

        if new_lat is None:
            no_match += 1
            print(f"[{i}/{total}] {name}: no Census match (keeping existing)")
        else:
            # Sanity check: don't accept wildly different positions
            if old_lat is not None and old_lng is not None:
                d_lat = abs(new_lat - float(old_lat))
                d_lng = abs(new_lng - float(old_lng))
                if d_lat > MAX_REASONABLE_DEGREES or d_lng > MAX_REASONABLE_DEGREES:
                    rejected_sanity += 1
                    print(f"[{i}/{total}] {name}: REJECTED Census ({new_lat:.5f},{new_lng:.5f}) - too far from previous, keeping ({old_lat:.5f},{old_lng:.5f})")
                    time.sleep(RATE_LIMIT_SECONDS)
                    continue

                if d_lat < 0.0001 and d_lng < 0.0001:
                    no_change += 1
                    print(f"[{i}/{total}] {name}: Census agrees with existing")
                else:
                    improved += 1
                    print(f"[{i}/{total}] {name}: UPDATED ({old_lat:.5f},{old_lng:.5f}) -> ({new_lat:.5f},{new_lng:.5f})")
            else:
                improved += 1
                print(f"[{i}/{total}] {name}: NEW ({new_lat:.5f},{new_lng:.5f})")

            loc["lat"] = new_lat
            loc["lng"] = new_lng

        time.sleep(RATE_LIMIT_SECONDS)

    with open(FILE, "w") as f:
        json.dump(data, f, indent=2)

    print(f"\n{'='*50}")
    print(f"Census geocoding done:")
    print(f"  Coords improved/updated:  {improved}")
    print(f"  Already had good coords:  {no_change}")
    print(f"  Census had no match:      {no_match}")
    print(f"  Rejected (sanity check):  {rejected_sanity}")


if __name__ == "__main__":
    main()
