"""
Positively Pittsburgh / CitySpark adapter.
Source: https://portal.cityspark.com/api/events/GetEvents/PopularPittsburgh
"""
import os
import json
import datetime
import requests

from adapters.base import BaseAdapter
import events as _ev_module

_ENDPOINT = "https://portal.cityspark.com/api/events/GetEvents/PopularPittsburgh"
_PAGE_SIZE = 100           # CitySpark returns up to 100 events per response
_MAX_PAGES = 40            # safety guard — normal stop is coverage-based, not page-count-based
_MIN_COVERAGE_DAYS = 30    # keep paging until events reach at least this many days ahead
_FETCH_WINDOW_DAYS = 90    # upper-bound sent to CitySpark; end:null returns only today's events
_TIMEOUT = 15              # seconds

# Pittsburgh-area center coordinates used for the CitySpark query.
# HOME_LAT / HOME_LNG drive the per-query sort; distance is recalculated
# server-side using the same env vars so cards always show miles from home.
_DEFAULT_LAT = 40.4383392333984
_DEFAULT_LNG = -79.9974670410156

_QUERY_LAT = float(os.environ.get("HOME_LAT", str(_DEFAULT_LAT)))
_QUERY_LNG = float(os.environ.get("HOME_LNG", str(_DEFAULT_LNG)))


def _fmt_price(val):
    """Format a price value cleanly: integer if whole-number, 2dp otherwise.
    Returns None for non-numeric strings like 'General Admission'."""
    if val is None:
        return None
    if isinstance(val, (int, float)):
        if float(val) == int(val):
            return str(int(val))
        return f"{val:.2f}"
    # String: strip leading $ and try numeric conversion
    try:
        f = float(str(val).lstrip("$").strip())
        if f == int(f):
            return str(int(f))
        return f"{f:.2f}"
    except (ValueError, TypeError):
        return None  # non-numeric string — discard


def _is_free_flag(val):
    """Return True only when a CitySpark Free/free field explicitly signals free.

    Accepts  : bool True, int/float 1, strings "true" / "True" / "1" (case-insensitive).
    Rejects  : bool False, 0, strings "false" / "0", None, any other value.
    Rationale: plain truthiness check (`if val`) would treat the string "false"
               as free — a real CitySpark edge-case we've observed.
    """
    if isinstance(val, bool):
        return val
    if isinstance(val, (int, float)):
        return val == 1
    if isinstance(val, str):
        return val.strip().lower() in ("true", "1")
    return False


def _parse_price(ev):
    """Return a clean admission string or None.

    Free check runs before price parsing and covers both capitalizations of the
    key ("Free" and "free") that CitySpark has been observed to use.
    """
    if _is_free_flag(ev.get("Free")) or _is_free_flag(ev.get("free")):
        return "Free"
    lo = _fmt_price(ev.get("Price"))
    hi = _fmt_price(ev.get("PriceHigh"))
    if lo and hi and lo != hi:
        return f"${lo}–${hi}"
    if lo:
        return f"${lo}"
    # CitySpark extended price fields (full undiscounted price)
    flo = _fmt_price(ev.get("LowFullPrice"))
    fhi = _fmt_price(ev.get("HighFullPrice"))
    if flo and fhi and flo != fhi:
        return f"${flo}–${fhi}"
    if flo:
        return f"${flo}"
    # PriceText as last resort — only use if it parses as a number
    pt = _fmt_price(ev.get("PriceText"))
    if pt:
        return f"${pt}"
    return None


def _best_url(ev):
    """Return the best event URL with the priority:
    PrimaryUrl → TicketUrl → Links[0].url → Tickets[0].url → None.
    Never returns a blank or non-http string."""
    def _http(s):
        s = (s or "").strip()
        return s if s.startswith("http") else None

    url = _http(ev.get("PrimaryUrl"))
    if url:
        return url
    url = _http(ev.get("TicketUrl"))
    if url:
        return url
    for lnk in (ev.get("Links") or []):
        url = _http(lnk.get("url"))
        if url:
            return url
    for t in (ev.get("Tickets") or []):
        url = _http(t.get("url") or t.get("Url"))
        if url:
            return url
    return None


def _event_date_str(ev):
    """Return YYYY-MM-DD from a CitySpark event's DateStart / StartUTC / Date, or ''.

    Intentionally date-only to avoid UTC/local off-by-one issues — we just need
    to know how far ahead CitySpark's results reach, not exact times.
    """
    for key in ("DateStart", "StartUTC", "Date"):
        val = ev.get(key)
        if val:
            s = str(val).strip()
            if len(s) >= 10 and s[4] == "-":
                return s[:10]
    return ""


def _parse_city_state(city_state):
    if not city_state:
        return None, None
    parts = [p.strip() for p in city_state.split(",")]
    city = parts[0] if parts else None
    state = parts[1][:2] if len(parts) > 1 else None
    return city, state


def _normalize(ev):
    city, state = _parse_city_state(ev.get("CityState"))
    start = ev.get("DateStart") or ev.get("Date")
    end = ev.get("DateEnd")

    def to_dt(s):
        if not s:
            return None
        try:
            dt = datetime.datetime.fromisoformat(s.replace("Z", "+00:00"))
            return dt.strftime("%Y-%m-%d %H:%M:%S")
        except Exception:
            return None

    start_dt = to_dt(start)
    end_dt = to_dt(end)

    date_label = None
    if start_dt:
        try:
            d = datetime.datetime.fromisoformat(start_dt)
            date_label = d.strftime("%a %b %-d")
            if end_dt:
                e = datetime.datetime.fromisoformat(end_dt)
                if d.date() != e.date():
                    date_label += "–" + e.strftime("%-d")
        except Exception:
            pass

    url = _best_url(ev)
    raw = json.dumps(ev, default=str, ensure_ascii=False)
    desc = (ev.get("Short") or ev.get("Description") or "")[:300]
    fp = _ev_module.make_fingerprint(ev.get("Name"), start_dt, ev.get("Venue"))

    return {
        "source_key": PositivelyPgh.source_key,
        "source_event_id": str(ev.get("Id") or ev.get("PId") or ""),
        "source_url": url,
        "official_url": url,
        "title": ev.get("Name", ""),
        "description_short": desc,
        "start_datetime": start_dt,
        "end_datetime": end_dt,
        "date_label": date_label,
        "venue_name": ev.get("Venue"),
        "address": ev.get("Address"),
        "city": city,
        "state": state,
        "postal_code": ev.get("Zip"),
        "latitude": ev.get("latitude"),
        "longitude": ev.get("longitude"),
        "category": None,
        "image_url": ev.get("MediumImg") or ev.get("SmallImg"),
        "admission": _parse_price(ev),
        "normalized_fingerprint": fp,
        "raw_source_json": raw,
    }


class PositivelyPgh(BaseAdapter):
    source_key = "positively_pgh"
    display_name = "Positively Pittsburgh"

    def fetch(self, coverage_days=30) -> list:
        # Clamp to valid range; fall back to 30 for any bad input.
        try:
            _cov = max(7, min(180, int(coverage_days)))
        except (ValueError, TypeError):
            _cov = _MIN_COVERAGE_DAYS
        print(f"[positively_pgh] coverage_days={_cov}")

        events = []
        seen_ids = set()
        now = datetime.datetime.utcnow()
        coverage_target = (now + datetime.timedelta(days=_cov)).strftime("%Y-%m-%d")
        start_str = now.strftime("%Y-%m-%dT00:00:00")
        end_str = (now + datetime.timedelta(days=_FETCH_WINDOW_DAYS)).strftime("%Y-%m-%dT23:59:59")

        skip = 0
        pages_fetched = 0
        latest_date_seen = ""  # furthest DateStart encountered across all fetched pages

        while pages_fetched < _MAX_PAGES:
            payload = {
                "ppid": 8462,
                "start": start_str,
                "end": end_str,  # explicit 90-day window; end:null returns only today's events
                "labels": [],
                "pick": False,
                "tps": None,
                "sparks": False,
                "sort": "Time",
                "category": [],
                "distance": 60,
                "lat": _QUERY_LAT,
                "lng": _QUERY_LNG,
                "search": "",
                "skip": skip,
                "defFilter": "all",
            }
            try:
                resp = requests.post(
                    _ENDPOINT,
                    json=payload,
                    timeout=_TIMEOUT,
                    headers={"Content-Type": "application/json"},
                )
                resp.raise_for_status()
                data = resp.json()
            except Exception as e:
                print(f"[positively_pgh] skip={skip} fetch error: {e}")
                break

            if not data.get("Success"):
                print(f"[positively_pgh] API returned Success=False: {data.get('ErrorMessage')}")
                break

            batch = data.get("Value") or []
            possible = data.get("Possible")  # total available events if provided
            pages_fetched += 1

            for ev in batch:
                # Track coverage from all events (including virtual) — measures
                # how far CitySpark's results reach, regardless of what we keep.
                ds = _event_date_str(ev)
                if ds > latest_date_seen:
                    latest_date_seen = ds

                # Skip virtual/online events — not relevant for local in-person listings.
                if ev.get("isVirtual"):
                    continue
                uid = str(ev.get("Id") or ev.get("PId") or "")
                if uid and uid in seen_ids:
                    continue
                if uid:
                    seen_ids.add(uid)
                events.append(_normalize(ev))

            if not batch or len(batch) < _PAGE_SIZE:
                break  # exhausted CitySpark results

            skip += len(batch)

            # If CitySpark reports a positive total, stop once we've fetched them all.
            if possible and skip >= possible:
                break

            # Coverage target reached — events at least _MIN_COVERAGE_DAYS ahead seen.
            if latest_date_seen >= coverage_target:
                break

        if pages_fetched >= _MAX_PAGES and latest_date_seen < coverage_target:
            print(
                f"[positively_pgh] WARNING: hit {_MAX_PAGES}-page cap before coverage target "
                f"— pages={pages_fetched}, skip={skip}, "
                f"latest={latest_date_seen or 'none'}, target={coverage_target} (coverage_days={_cov})"
            )
        print(
            f"[positively_pgh] {len(events)} events in {pages_fetched} page(s), "
            f"latest={latest_date_seen or 'none'}, target={coverage_target} (coverage_days={_cov})"
        )
        return events
