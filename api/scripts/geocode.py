#!/usr/bin/env python3
"""
Geocode the locations in mollies_guide.json using Nominatim (OpenStreetMap).

Nominatim usage policy:
- Max 1 request per second
- Must include a meaningful User-Agent
- See https://operations.osmfoundation.org/policies/nominatim/

Output: mollies_guide_geocoded.json with lat/lng filled in.
"""

import json
import time
import sys
from pathlib import Path
import requests

# Paths
DATA_DIR = Path(__file__).resolve().parent.parent / "data"
INPUT_FILE = DATA_DIR / "mollies_guide.json"
OUTPUT_FILE = DATA_DIR / "mollies_guide_geocoded.json"

# Nominatim
NOMINATIM_URL = "https://nominatim.openstreetmap.org/search"
USER_AGENT = "MolliesGuide/1.0 (charlie - personal use)"
RATE_LIMIT_SECONDS = 1.1  # bit over 1s to be safe


def geocode_address(address, city, state, zip_code):
    """Try Nominatim with progressively looser queries until something hits."""
    queries = [
        # Most specific first
        f"{address}, {city}, {state} {zip_code}",
        f"{address}, {city}, {state}",
        f"{city}, {state} {zip_code}",
    ]
    for q in queries:
        try:
            r = requests.get(
                NOMINATIM_URL,
                params={
                    "q": q,
                    "format": "json",
                    "limit": 1,
                    "countrycodes": "us",
                },
                headers={"User-Agent": USER_AGENT},
                timeout=15,
            )
            r.raise_for_status()
            results = r.json()
            if results:
                return float(results[0]["lat"]), float(results[0]["lon"]), q
        except requests.RequestException as e:
            print(f"    request error on '{q}': {e}", file=sys.stderr)
        time.sleep(RATE_LIMIT_SECONDS)
    return None, None, None


def main():
    if not INPUT_FILE.exists():
        print(f"ERROR: {INPUT_FILE} not found", file=sys.stderr)
        sys.exit(1)

    with open(INPUT_FILE) as f:
        data = json.load(f)

    locations = data["locations"]
    total = len(locations)
    success = 0
    failed = []

    # Resume support: if output file already exists, copy any existing coords
    existing_coords = {}
    if OUTPUT_FILE.exists():
        with open(OUTPUT_FILE) as f:
            existing = json.load(f)
        for loc in existing.get("locations", []):
            if loc.get("lat") is not None and loc.get("lng") is not None:
                key = (loc.get("name"), loc.get("address"))
                existing_coords[key] = (loc["lat"], loc["lng"])
        print(f"Resuming - {len(existing_coords)} locations already geocoded")

    print(f"Geocoding {total} locations (this will take ~{total * 2}s)...\n")

    for i, loc in enumerate(locations, 1):
        name = loc.get("name", "(unnamed)")
        key = (loc.get("name"), loc.get("address"))

        # Skip if already geocoded from a previous run
        if key in existing_coords:
            loc["lat"], loc["lng"] = existing_coords[key]
            success += 1
            print(f"[{i}/{total}] {name}: cached")
            continue

        addr = loc.get("address", "")
        city = loc.get("city", "")
        state = loc.get("state", "")
        zip_code = loc.get("zip", "")

        if not addr or not city:
            print(f"[{i}/{total}] {name}: SKIP (missing address/city)")
            failed.append(name)
            loc["lat"] = None
            loc["lng"] = None
            continue

        lat, lng, matched_query = geocode_address(addr, city, state, zip_code)
        if lat is not None:
            loc["lat"] = lat
            loc["lng"] = lng
            success += 1
            print(f"[{i}/{total}] {name}: ({lat:.5f}, {lng:.5f}) via '{matched_query}'")
        else:
            failed.append(name)
            loc["lat"] = None
            loc["lng"] = None
            print(f"[{i}/{total}] {name}: FAILED")

        # Save progress after each one in case we get interrupted
        with open(OUTPUT_FILE, "w") as f:
            json.dump(data, f, indent=2)

    print(f"\n{'='*50}")
    print(f"Done. {success}/{total} geocoded successfully.")
    if failed:
        print(f"\n{len(failed)} failed - manual lookup needed:")
        for name in failed:
            print(f"  - {name}")
    print(f"\nOutput written to: {OUTPUT_FILE}")


if __name__ == "__main__":
    main()
