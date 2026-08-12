"""
Shared base adapter for WordPress sites running The Events Calendar (Tribe) plugin.

These sites expose a clean JSON REST API at:
    /wp-json/tribe/events/v1/events

Subclasses set source_key, display_name, and api_base; all fetch/normalize logic
lives here so new venues need only a 3-line file.

Attribution: events link back to each venue's own event pages via source_url.
"""
import html as _html_mod
import json
import re
import datetime
import requests
from zoneinfo import ZoneInfo

from adapters.base import BaseAdapter
from adapters.utils import FetchResult, REGIONAL_TZ, utc_naive_string
import events as _ev_module

_PER_PAGE = 100   # Tribe API max per page
_MAX_PAGES = 10   # hard safety cap per refresh
_TIMEOUT   = 15   # seconds


# ── Text helpers ──────────────────────────────────────────────────────────────

def _strip_html(s):
    """Strip HTML tags, collapse whitespace, decode entities."""
    if not s:
        return None
    s = re.sub(r'<[^>]+>', ' ', s)
    s = _html_mod.unescape(s)
    s = ' '.join(s.split())
    # Remove spaces that were introduced before punctuation by tag removal.
    s = re.sub(r' ([.,;:!?])', r'\1', s)
    return s or None


# ── Price parsing ─────────────────────────────────────────────────────────────

def _parse_tribe_cost(ev):
    """Return normalized admission string from a Tribe event dict, or None."""
    cost_str = (ev.get('cost') or '').strip()
    values    = (ev.get('cost_details') or {}).get('values') or []

    if cost_str.lower() == 'free':
        return 'Free'

    try:
        nums = [float(v) for v in values if v is not None]
    except (TypeError, ValueError):
        nums = []

    if nums:
        lo, hi = min(nums), max(nums)
        def _fmt(n):
            return str(int(n)) if n == int(n) else f'{n:.2f}'
        if lo == hi:
            return 'Free' if lo == 0 else f'${_fmt(lo)}'
        return f'${_fmt(lo)}–${_fmt(hi)}'

    if cost_str:
        # Accept "$X", "X", or text like "Members free" — store raw
        return cost_str

    return None


# ── Normalizer ────────────────────────────────────────────────────────────────

def _normalize(ev, source_key):
    """
    Convert a Tribe Events API event dict into the common event schema.
    Returns None if the event is virtual and should be skipped.
    """
    if ev.get('is_virtual'):
        return None

    title = _strip_html(ev.get('title')) or ''

    # Short description from excerpt (never full HTML description)
    desc = _strip_html(ev.get('excerpt') or '')
    if desc and len(desc) > 280:
        desc = desc[:277] + '…'

    # Prefer explicit UTC values. Otherwise interpret provider wall-clock values
    # in its declared IANA timezone, falling back to the Pittsburgh region.
    try:
        source_tz = ZoneInfo(ev.get('timezone')) if ev.get('timezone') else REGIONAL_TZ
    except Exception:
        source_tz = REGIONAL_TZ
    start_dt = utc_naive_string(ev.get('utc_start_date'), ZoneInfo('UTC')) \
        if ev.get('utc_start_date') else utc_naive_string(ev.get('start_date'), source_tz)
    end_dt = utc_naive_string(ev.get('utc_end_date'), ZoneInfo('UTC')) \
        if ev.get('utc_end_date') else utc_naive_string(ev.get('end_date'), source_tz)

    date_label = None
    if start_dt:
        try:
            if ev.get('start_date'):
                label_dt = datetime.datetime.fromisoformat(str(ev['start_date']).replace('Z', '+00:00'))
            else:
                label_dt = datetime.datetime.strptime(start_dt, '%Y-%m-%d %H:%M:%S').replace(
                    tzinfo=ZoneInfo('UTC')).astimezone(source_tz)
            date_label = label_dt.strftime('%a %b %-d')
        except Exception:
            pass

    # Venue
    vd        = ev.get('venue') or {}
    if isinstance(vd, list):
        vd = next((item for item in vd if isinstance(item, dict)), {})
    venue_name = _strip_html(vd.get('venue') or '') or None
    address    = vd.get('address') or None
    city       = (vd.get('city') or '').strip().title() or None  # "pittsburgh" → "Pittsburgh"
    state      = vd.get('stateprovince') or vd.get('state') or None
    postal     = vd.get('zip') or None
    geo_lat    = vd.get('geo_lat') or None
    geo_lng    = vd.get('geo_lng') or None

    # URLs — prefer website (ticket/info page) as official, event page as source
    official_url = ev.get('website') or ev.get('url') or None
    source_url   = ev.get('url') or official_url

    # Image — use the full-size URL from the image block
    img       = ev.get('image') or {}
    image_url = img.get('url') if isinstance(img, dict) else None

    # Category — first category name, HTML-decoded
    cats     = ev.get('categories') or []
    category = _html_mod.unescape(cats[0].get('name', '')) if cats else None

    admission = _parse_tribe_cost(ev)

    # Occurrence fingerprint: source_key + upstream event ID + full start datetime
    fp = _ev_module.make_fingerprint(
        source_key, str(ev.get('id') or ''), start_dt,
        title, venue_name or source_url
    )
    # Series key: source_key + title (no date) — for future recurring-event queries
    sk = _ev_module.make_series_key(source_key, title)

    # Raw JSON — omit full HTML description to keep rows compact
    raw_ev = {k: v for k, v in ev.items() if k != 'description'}
    raw    = json.dumps(raw_ev, default=str, ensure_ascii=False)

    return {
        'source_key':            source_key,
        'source_event_id':       str(ev.get('id') or ''),
        'source_url':            source_url,
        'official_url':          official_url,
        'title':                 title,
        'description_short':     desc or None,
        'start_datetime':        start_dt,
        'end_datetime':          end_dt,
        'date_label':            date_label,
        'venue_name':            venue_name,
        'address':               address,
        'city':                  city,
        'state':                 state,
        'postal_code':           postal,
        'latitude':              geo_lat,
        'longitude':             geo_lng,
        'category':              category,
        'image_url':             image_url,
        'admission':             admission,
        'normalized_fingerprint': fp,
        'series_key':            sk,
        'raw_source_json':       raw,
    }


# ── Base adapter class ────────────────────────────────────────────────────────

class TribeEventsAdapter(BaseAdapter):
    """
    Base class for WordPress + The Events Calendar (Tribe) sites.

    Subclasses must define:
        source_key   : str  — unique slug, e.g. "heinz_history"
        display_name : str  — human label, e.g. "Heinz History Center"
        api_base     : str  — site root, e.g. "https://www.heinzhistorycenter.org"
    """
    api_base: str = None

    def fetch(self, coverage_days=60) -> list:
        try:
            cov = max(7, min(180, int(coverage_days)))
        except (ValueError, TypeError):
            cov = 60

        now      = datetime.datetime.utcnow()
        start_str = now.strftime('%Y-%m-%dT00:00:00')
        end_str   = (now + datetime.timedelta(days=cov)).strftime('%Y-%m-%dT23:59:59')
        endpoint  = self.api_base.rstrip('/') + '/wp-json/tribe/events/v1/events'

        print(f'[{self.source_key}] coverage_days={cov}'
              f' window={start_str[:10]} → {end_str[:10]}')

        events   = []
        seen_occurrences = set()
        failure = None

        for page in range(1, _MAX_PAGES + 1):
            params = {
                'per_page':   _PER_PAGE,
                'start_date': start_str,
                'end_date':   end_str,
                'status':     'publish',
                'page':       page,
            }
            try:
                resp = requests.get(
                    endpoint, params=params, timeout=_TIMEOUT,
                    headers={'Accept': 'application/json',
                             'User-Agent': 'EventMapApp/1.0 (local private app)'}
                )
                resp.raise_for_status()
                data = resp.json()
            except Exception as e:
                print(f'[{self.source_key}] fetch error page={page}: {e}')
                failure = f"page {page}: {e}"
                break

            batch       = data.get('events') or []
            total_pages = int(data.get('total_pages') or 1)

            for ev in batch:
                eid = str(ev.get('id') or '')
                occurrence_key = (eid, ev.get('utc_start_date') or ev.get('start_date') or '')
                if eid and occurrence_key in seen_occurrences:
                    continue
                if eid:
                    seen_occurrences.add(occurrence_key)
                normalized = _normalize(ev, self.source_key)
                if normalized is not None:
                    events.append(normalized)

            if not batch or page >= total_pages:
                break

        print(f'[{self.source_key}] {len(events)} events fetched')
        return FetchResult(events, complete=failure is None, error=failure)
