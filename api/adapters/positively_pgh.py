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
_PAGE_SIZE = 25
_MAX_PAGES = 8   # fetch up to 200 events per refresh
_TIMEOUT = 15    # seconds

# Pittsburgh-area center coordinates used for the CitySpark query.
# If HOME_LAT / HOME_LNG are set, use those instead so results are
# sorted by distance from home (server-to-server only, never exposed to browser).
_DEFAULT_LAT = 40.4383392333984
_DEFAULT_LNG = -79.9974670410156

_QUERY_LAT = float(os.environ.get("HOME_LAT", str(_DEFAULT_LAT)))
_QUERY_LNG = float(os.environ.get("HOME_LNG", str(_DEFAULT_LNG)))


def _parse_price(ev):
    if ev.get("Free"):
        return "Free"
    price = ev.get("Price") or ev.get("PriceText")
    high = ev.get("PriceHigh")
    if price and high and price != high:
        return f"${price}–${high}"
    if price:
        return f"${price}"
    return None


def _parse_city_state(city_state):
    if not city_state:
        return None, None
    parts = [p.strip() for p in city_state.split(",")]
    city = parts[0] if parts else None
    state = parts[1][:2] if len(parts) > 1 else None
    return city, state


def _best_url(ev):
    primary = ev.get("PrimaryUrl") or ""
    links = ev.get("Links") or []
    for lnk in links:
        url = lnk.get("url", "")
        if url and url.startswith("http"):
            return url
    return primary or None


def _normalize(ev):
    city, state = _parse_city_state(ev.get("CityState"))
    start = ev.get("DateStart") or ev.get("Date")
    end = ev.get("DateEnd")

    # Normalize ISO timestamps to YYYY-MM-DD HH:MM:SS for MySQL
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
    raw = json.dumps(ev, default=str)[:4000]

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

    def fetch(self) -> list:
        events = []
        seen_ids = set()
        now = datetime.datetime.utcnow()
        start_str = now.strftime("%Y-%m-%dT00:00:00")

        for page in range(_MAX_PAGES):
            payload = {
                "ppid": 8462,
                "start": start_str,
                "end": None,
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
                "skip": page * _PAGE_SIZE,
                "defFilter": "all",
            }
            try:
                resp = requests.post(
                    _ENDPOINT,
                    json=payload,
                    timeout=_TIMEOUT,
                    headers={"Content-Type": "application/json"}
                )
                resp.raise_for_status()
                data = resp.json()
            except Exception as e:
                print(f"[positively_pgh] page {page} fetch error: {e}")
                break

            if not data.get("Success"):
                print(f"[positively_pgh] API returned Success=False: {data.get('ErrorMessage')}")
                break

            batch = data.get("Value") or []
            for ev in batch:
                uid = str(ev.get("Id") or ev.get("PId") or "")
                if uid and uid in seen_ids:
                    continue
                if uid:
                    seen_ids.add(uid)
                events.append(_normalize(ev))

            if len(batch) < _PAGE_SIZE:
                break  # last page

        return events
