"""
Visit Pittsburgh adapter — uses the public Algolia site search index.

Fetches structured calendar events (sectionHandle=events, typeHandle=event).
These have real Unix-timestamp start/end dates, venue/address info, and
external website links.

Algolia search credentials are public read-only keys embedded in the
visitpittsburgh.com site HTML — they are not private secrets.
"""
import os
import re
import json
import datetime
import requests

from adapters.base import BaseAdapter
import events as _ev_module

_APP_ID   = os.environ.get("VP_ALGOLIA_APP_ID",  "EYQHJ2IY2M")
_API_KEY  = os.environ.get("VP_ALGOLIA_API_KEY",  "c6d5977cb5cd80c09abfd2a7e5d9e88b")
_INDEX    = os.environ.get("VP_ALGOLIA_INDEX",    "prod-visit-pittsburgh")
_BASE_URL = "https://www.visitpittsburgh.com"
_ENDPOINT = f"https://{_APP_ID}-dsn.algolia.net/1/indexes/{_INDEX}/query"
_TIMEOUT  = 15

_STATE_MAP = {
    "Pennsylvania": "PA", "Ohio": "OH", "West Virginia": "WV",
    "New York": "NY", "Maryland": "MD", "Delaware": "DE",
    "New Jersey": "NJ", "Virginia": "VA",
}

_ATTRS = [
    "title", "uri", "snippet", "content", "primaryImageUrl",
    "typeHandle", "sectionHandle", "startDate", "endDate",
    "address", "website", "eventCategories", "objectID", "id",
]


def _parse_address(addr_list):
    """Return (venue, street, city, state, postal) from Algolia address array."""
    if not addr_list:
        return None, None, None, None, None
    venue  = addr_list[0] if len(addr_list) > 0 else None
    street = addr_list[1] if len(addr_list) > 1 else None
    city_state_zip = addr_list[2] if len(addr_list) > 2 else None
    city = state = postal = None

    if city_state_zip:
        m = re.match(r'^(.+?),\s*([A-Za-z ]+?)\s*(\d{5})?\s*$', city_state_zip.strip())
        if m:
            city = m.group(1).strip() or None
            state_raw = m.group(2).strip()
            postal = m.group(3)
            state = _STATE_MAP.get(state_raw, state_raw[:2].upper() if len(state_raw) <= 2 else None)
        else:
            # address[2] has no city component (e.g. ", Pennsylvania 15129")
            m2 = re.match(r'^,?\s*([A-Za-z ]+?)\s*(\d{5})?\s*$', city_state_zip.strip())
            if m2:
                state_raw = m2.group(1).strip()
                postal = m2.group(2)
                state = _STATE_MAP.get(state_raw, state_raw[:2].upper() if len(state_raw) <= 2 else None)

    # If city still None, parse "Street, City, ST ZIP" from address[1]
    if city is None and street:
        parts = [p.strip() for p in street.split(',')]
        if len(parts) >= 3:
            city = parts[-2]
            if state is None:
                last = parts[-1].strip()
                m3 = re.match(r'^([A-Z]{2})\s*(\d{5})?$', last)
                if m3:
                    state = m3.group(1)
                    if postal is None:
                        postal = m3.group(2)

    return venue, street, city, state, postal


def _ts_to_dt(ts):
    if not ts:
        return None
    try:
        dt = datetime.datetime.utcfromtimestamp(int(ts))
        return dt.strftime("%Y-%m-%d %H:%M:%S")
    except Exception:
        return None


def _normalize(hit):
    uri = hit.get("uri") or ""
    source_url = _BASE_URL + "/" + uri.lstrip("/")
    official_url = hit.get("website") or source_url
    title = hit.get("title") or ""

    content = hit.get("content") or hit.get("snippet") or ""
    description = content[:280] if content else None

    image = hit.get("primaryImageUrl")
    if image and image.lower().endswith(".pdf"):
        image = None

    start_dt = _ts_to_dt(hit.get("startDate"))
    end_dt   = _ts_to_dt(hit.get("endDate"))

    date_label = "See website"
    if start_dt:
        try:
            d = datetime.datetime.strptime(start_dt, "%Y-%m-%d %H:%M:%S").date()
            date_label = d.strftime("%a %b %-d")
        except ValueError:
            pass

    venue, street, city, state, postal = _parse_address(hit.get("address"))

    cats = hit.get("eventCategories") or []
    category = cats[0] if cats else "event"

    object_id = str(hit.get("objectID") or hit.get("id") or "")
    date_str = start_dt[:10] if start_dt else None
    fp = _ev_module.make_fingerprint(title, date_str, venue or source_url)

    raw = json.dumps({k: v for k, v in hit.items() if not k.startswith("_")}, default=str, ensure_ascii=False)

    return {
        "source_key": VisitPittsburgh.source_key,
        "source_event_id": object_id,
        "source_url": source_url,
        "official_url": official_url,
        "title": title,
        "description_short": description,
        "start_datetime": start_dt,
        "end_datetime": end_dt,
        "date_label": date_label,
        "venue_name": venue,
        "address": street,
        "city": city,
        "state": state,
        "postal_code": postal,
        "latitude": None,
        "longitude": None,
        "category": category,
        "image_url": image,
        "admission": None,
        "normalized_fingerprint": fp,
        "raw_source_json": raw,
    }


class VisitPittsburgh(BaseAdapter):
    source_key = "visit_pittsburgh"
    display_name = "Visit Pittsburgh"

    def fetch(self) -> list:
        headers = {
            "X-Algolia-Application-Id": _APP_ID,
            "X-Algolia-API-Key": _API_KEY,
            "Content-Type": "application/json",
        }

        now_ts = datetime.datetime.utcnow().timestamp()
        # Allow events that ended up to 1 day ago (stale-cache tolerance)
        cutoff_ts = now_ts - 86400

        seen_ids = set()
        events = []

        # Two queries: "2026" for upcoming year-labelled events,
        # "pittsburgh" for recurring/unlabelled events not captured by year query.
        year = datetime.date.today().year
        for query in [str(year), "pittsburgh"]:
            for page in range(5):
                payload = {
                    "query": query,
                    "hitsPerPage": 100,
                    "page": page,
                    "attributesToRetrieve": _ATTRS,
                }
                try:
                    resp = requests.post(
                        _ENDPOINT, headers=headers, json=payload, timeout=_TIMEOUT
                    )
                    resp.raise_for_status()
                    data = resp.json()
                except Exception as e:
                    print(f"[visit_pittsburgh] fetch error (query={query!r}, page={page}): {e}")
                    break

                hits = data.get("hits") or []
                nb_pages = data.get("nbPages", 1)

                for hit in hits:
                    if hit.get("typeHandle") != "event":
                        continue
                    uri = hit.get("uri") or ""
                    if "/blog/" in uri or "/articles/" in uri:
                        continue

                    obj_id = str(hit.get("objectID") or hit.get("id") or "")
                    if obj_id and obj_id in seen_ids:
                        continue

                    end_ts = hit.get("endDate") or hit.get("startDate") or 0
                    if end_ts and end_ts < cutoff_ts:
                        continue

                    if obj_id:
                        seen_ids.add(obj_id)

                    events.append(_normalize(hit))

        return events
