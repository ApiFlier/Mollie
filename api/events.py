"""
External events core module: refresh, dedupe, distance, cache, query.
"""
import hashlib
import math
import os
import datetime
import threading

def _parse_float_env(name, default, min_val=None, max_val=None):
    """Return float from env var, falling back to default on blank/invalid/out-of-range."""
    raw = os.environ.get(name, "").strip()
    if not raw:
        return default
    try:
        val = float(raw)
    except (ValueError, TypeError):
        print(f"[events] WARNING: {name}={raw!r} is not a valid float; using default {default}")
        return default
    if (min_val is not None and val < min_val) or (max_val is not None and val > max_val):
        print(f"[events] WARNING: {name}={val} out of range [{min_val}, {max_val}]; using default {default}")
        return default
    return val


# Home coordinates for distance calculations.
# Source of truth: HOME_LAT / HOME_LNG in .env → docker-compose environment.
# Defaults: 133 Courtney Drive, Verona, PA 15147.
HOME_LAT = _parse_float_env("HOME_LAT", 40.487993, min_val=-90.0, max_val=90.0)
HOME_LNG = _parse_float_env("HOME_LNG", -79.805208, min_val=-180.0, max_val=180.0)

CACHE_HOURS = int(os.environ.get("EVENTS_CACHE_HOURS", "24"))

_ADAPTERS: dict = {}
_refresh_lock = threading.Lock()
_refresh_running = False


# ── Adapter registry ──────────────────────────────────────────────────────────

def register_adapter(adapter):
    _ADAPTERS[adapter.source_key] = adapter


def get_adapters():
    return dict(_ADAPTERS)


# ── Distance ──────────────────────────────────────────────────────────────────

def haversine_miles(lat1, lng1, lat2, lng2):
    R = 3958.8
    lat1, lng1, lat2, lng2 = (math.radians(x) for x in [float(lat1), float(lng1), float(lat2), float(lng2)])
    dlat = lat2 - lat1
    dlng = lng2 - lng1
    a = math.sin(dlat / 2) ** 2 + math.cos(lat1) * math.cos(lat2) * math.sin(dlng / 2) ** 2
    return R * 2 * math.asin(math.sqrt(min(1.0, a)))


def compute_distance(lat, lng):
    """Returns (distance_miles, estimated_drive_minutes) or (None, None)."""
    if lat is None or lng is None:
        return None, None
    try:
        dist = haversine_miles(HOME_LAT, HOME_LNG, lat, lng)
        return round(dist, 1), round(dist * 1.35)
    except Exception:
        return None, None


def recalculate_all_distances(conn):
    """Recompute distance_miles / estimated_drive_minutes for all stored events from current HOME."""
    cur = conn.cursor(dictionary=True)
    cur.execute("SELECT id, latitude, longitude FROM external_events WHERE latitude IS NOT NULL AND longitude IS NOT NULL")
    rows = cur.fetchall()
    cur.close()
    if not rows:
        return
    updates = []
    for r in rows:
        dist, drive = compute_distance(r["latitude"], r["longitude"])
        if dist is not None:
            updates.append((dist, drive, r["id"]))
    if updates:
        cur2 = conn.cursor()
        cur2.executemany(
            "UPDATE external_events SET distance_miles=%s, estimated_drive_minutes=%s WHERE id=%s",
            updates,
        )
        conn.commit()
        cur2.close()
    print(f"[events] Recalculated distances for {len(updates)} events from ({HOME_LAT}, {HOME_LNG}).")


# ── Fingerprint ───────────────────────────────────────────────────────────────

def make_fingerprint(title, date_str, venue_or_url):
    parts = [
        (title or "").lower().strip(),
        (date_str or "")[:10],
        (venue_or_url or "").lower().strip(),
    ]
    return hashlib.md5("|".join(parts).encode()).hexdigest()


# ── Staleness check ───────────────────────────────────────────────────────────

def _is_stale(conn, source_key):
    cur = conn.cursor(dictionary=True)
    cur.execute(
        "SELECT last_success_at FROM event_sources WHERE source_key = %s",
        (source_key,)
    )
    row = cur.fetchone()
    cur.close()
    if not row or not row["last_success_at"]:
        return True
    threshold = datetime.datetime.utcnow() - datetime.timedelta(hours=CACHE_HOURS)
    return row["last_success_at"] < threshold


def any_source_stale(conn):
    for key in _ADAPTERS:
        if _is_stale(conn, key):
            return True
    return False


# ── DB helpers ────────────────────────────────────────────────────────────────

def _ensure_source(conn, source_key, display_name):
    cur = conn.cursor()
    cur.execute(
        """INSERT INTO event_sources (source_key, display_name)
           VALUES (%s, %s)
           ON DUPLICATE KEY UPDATE display_name = %s""",
        (source_key, display_name, display_name)
    )
    conn.commit()
    cur.close()


def _mark_success(conn, source_key):
    cur = conn.cursor()
    cur.execute(
        "UPDATE event_sources SET last_success_at=NOW(), last_attempt_at=NOW(), last_error=NULL WHERE source_key=%s",
        (source_key,)
    )
    conn.commit()
    cur.close()


def _mark_error(conn, source_key, error):
    cur = conn.cursor()
    cur.execute(
        "UPDATE event_sources SET last_attempt_at=NOW(), last_error=%s WHERE source_key=%s",
        (str(error)[:1000], source_key)
    )
    conn.commit()
    cur.close()


# ── Upsert ────────────────────────────────────────────────────────────────────

def _score(ev):
    return (
        bool(ev.get("image_url")) * 4 +
        bool(ev.get("latitude")) * 2 +
        bool(ev.get("official_url")) * 1
    )


def _upsert_event(conn, ev):
    fp = ev.get("normalized_fingerprint")
    dist, drive = compute_distance(ev.get("latitude"), ev.get("longitude"))
    ev["distance_miles"] = dist
    ev["estimated_drive_minutes"] = drive

    cur = conn.cursor(dictionary=True)
    cur.execute(
        "SELECT id, source_key, image_url, latitude, official_url FROM external_events WHERE normalized_fingerprint = %s",
        (fp,)
    )
    existing = cur.fetchone()
    cur.close()

    if existing:
        existing_id = existing["id"]
        if existing["source_key"] != ev["source_key"]:
            if _score(ev) > _score(existing):
                _do_update(conn, existing_id, ev)
            else:
                cur2 = conn.cursor()
                cur2.execute("UPDATE external_events SET last_seen_at=NOW() WHERE id=%s", (existing_id,))
                cur2.close()
        else:
            _do_update(conn, existing_id, ev)
    else:
        _do_insert(conn, ev)


def _do_update(conn, event_id, ev):
    cur = conn.cursor()
    cur.execute(
        """UPDATE external_events SET
             source_url=%s, official_url=%s, title=%s, description_short=%s,
             start_datetime=%s, end_datetime=%s, date_label=%s,
             venue_name=%s, address=%s, city=%s, state=%s, postal_code=%s,
             latitude=%s, longitude=%s, category=%s, image_url=%s, admission=%s,
             distance_miles=%s, estimated_drive_minutes=%s,
             last_seen_at=NOW(), updated_at=NOW()
           WHERE id=%s""",
        (
            ev.get("source_url"), ev.get("official_url"), ev.get("title"),
            ev.get("description_short"),
            ev.get("start_datetime"), ev.get("end_datetime"), ev.get("date_label"),
            ev.get("venue_name"), ev.get("address"), ev.get("city"),
            ev.get("state"), ev.get("postal_code"),
            ev.get("latitude"), ev.get("longitude"), ev.get("category"),
            ev.get("image_url"), ev.get("admission"),
            ev.get("distance_miles"), ev.get("estimated_drive_minutes"),
            event_id,
        )
    )
    cur.close()


def _do_insert(conn, ev):
    cur = conn.cursor()
    cur.execute(
        """INSERT INTO external_events (
             source_key, source_event_id, source_url, official_url,
             title, description_short, start_datetime, end_datetime, date_label,
             venue_name, address, city, state, postal_code,
             latitude, longitude, category, image_url, admission,
             distance_miles, estimated_drive_minutes,
             normalized_fingerprint, raw_source_json
           ) VALUES (
             %s,%s,%s,%s, %s,%s,%s,%s,%s, %s,%s,%s,%s,%s,
             %s,%s,%s,%s,%s, %s,%s, %s,%s
           )""",
        (
            ev.get("source_key"), ev.get("source_event_id"),
            ev.get("source_url"), ev.get("official_url"),
            ev.get("title"), ev.get("description_short"),
            ev.get("start_datetime"), ev.get("end_datetime"), ev.get("date_label"),
            ev.get("venue_name"), ev.get("address"), ev.get("city"),
            ev.get("state"), ev.get("postal_code"),
            ev.get("latitude"), ev.get("longitude"),
            ev.get("category"), ev.get("image_url"), ev.get("admission"),
            ev.get("distance_miles"), ev.get("estimated_drive_minutes"),
            ev.get("normalized_fingerprint"), ev.get("raw_source_json"),
        )
    )
    cur.close()


# ── Refresh ───────────────────────────────────────────────────────────────────

def refresh_source(conn, source_key):
    """Fetch and upsert events for one source. Returns count of events upserted."""
    adapter = _ADAPTERS.get(source_key)
    if not adapter:
        raise ValueError(f"Unknown source: {source_key}")

    _ensure_source(conn, source_key, adapter.display_name)

    try:
        events = adapter.fetch()
    except Exception as e:
        print(f"[events] {source_key} fetch failed: {e}")
        _mark_error(conn, source_key, e)
        return 0

    count = 0
    for ev in events:
        try:
            _upsert_event(conn, ev)
            count += 1
        except Exception as e:
            print(f"[events] upsert error for '{ev.get('title', '?')}': {e}")

    conn.commit()
    _mark_success(conn, source_key)
    print(f"[events] {source_key}: {count} events upserted")
    return count


def refresh_all(conn):
    """Refresh all enabled sources. Returns {source_key: count}."""
    results = {}
    for key in list(_ADAPTERS.keys()):
        results[key] = refresh_source(conn, key)
    return results


def refresh_all_stale(conn):
    """Refresh only stale sources."""
    results = {}
    for key in list(_ADAPTERS.keys()):
        if _is_stale(conn, key):
            results[key] = refresh_source(conn, key)
    return results


def trigger_background_refresh(get_conn_fn):
    """Fire-and-forget background refresh. Safe to call on every stale GET /api/events."""
    global _refresh_running
    if _refresh_running:
        return
    with _refresh_lock:
        if _refresh_running:
            return
        _refresh_running = True

    def _run():
        global _refresh_running
        try:
            conn = get_conn_fn()
            try:
                refresh_all_stale(conn)
            finally:
                conn.close()
        except Exception as e:
            print(f"[events] background refresh error: {e}")
        finally:
            _refresh_running = False

    t = threading.Thread(target=_run, daemon=True)
    t.start()


# ── Query ─────────────────────────────────────────────────────────────────────

def get_enabled_source_keys(conn):
    """Return a set of enabled source_keys from event_sources."""
    cur = conn.cursor()
    cur.execute("SELECT source_key FROM event_sources WHERE enabled = TRUE")
    keys = {row[0] for row in cur.fetchall()}
    cur.close()
    return keys


def get_sources(conn, enabled_only=True):
    """Return source rows from event_sources."""
    cur = conn.cursor(dictionary=True)
    if enabled_only:
        cur.execute(
            "SELECT source_key, display_name, enabled FROM event_sources WHERE enabled = TRUE ORDER BY source_key"
        )
    else:
        cur.execute(
            "SELECT source_key, display_name, enabled FROM event_sources ORDER BY source_key"
        )
    rows = cur.fetchall()
    cur.close()
    return rows


def get_events(conn, filter_type=None, sort=None, saved_only=False,
               max_drive_min=None, max_distance_miles=None,
               date_filter=None, start_date=None, end_date=None,
               source_keys=None, enabled_only=True,
               limit=100, offset=0):
    """
    Return non-hidden external_events from the cache.

    date_filter       : 'today' | 'this_weekend' | 'custom' | None
    start_date        : 'YYYY-MM-DD' (used when date_filter='custom')
    end_date          : 'YYYY-MM-DD' (used when date_filter='custom'; inclusive)
    sort              : 'soonest' | 'closest'
    saved_only        : bool
    max_distance_miles: float | None — filter by distance_miles from home
    max_drive_min     : int | None — legacy fallback, prefer max_distance_miles
    filter_type       : legacy 'this_weekend' alias
    source_keys       : list of source_key strings to restrict results (public filter)
    enabled_only      : if True, only return events from enabled sources (public default)
    limit / offset    : pagination
    """
    now = datetime.datetime.utcnow()
    conditions = ["hidden = FALSE"]
    params = []

    if saved_only:
        conditions.append("saved = TRUE")

    # Show future events (with 6-hour grace for in-progress events)
    conditions.append("(start_datetime IS NULL OR start_datetime >= %s)")
    params.append(now - datetime.timedelta(hours=6))

    # Normalise legacy filter_type → date_filter
    effective_date = date_filter or (filter_type if filter_type in ("today", "this_weekend") else None)

    if effective_date == "today":
        today_start = now.replace(hour=0, minute=0, second=0, microsecond=0)
        today_end = today_start + datetime.timedelta(days=1)
        conditions.append("(start_datetime BETWEEN %s AND %s OR start_datetime IS NULL)")
        params.extend([today_start, today_end])

    elif effective_date == "this_weekend":
        # Include Friday 00:00 through Sunday 23:59 of the current (or upcoming) weekend.
        weekday = now.weekday()  # Mon=0 … Sun=6
        if weekday <= 4:         # Mon–Fri: use this/next Friday
            days_to_fri = 4 - weekday
        else:                    # Sat(5) → -1, Sun(6) → -2: roll back to Friday
            days_to_fri = -(weekday - 4)
        fri = (now + datetime.timedelta(days=days_to_fri)).replace(hour=0, minute=0, second=0, microsecond=0)
        sun_end = (fri + datetime.timedelta(days=2)).replace(hour=23, minute=59, second=59)
        conditions.append("(start_datetime BETWEEN %s AND %s OR start_datetime IS NULL)")
        params.extend([fri, sun_end])

    elif effective_date == "custom" and start_date:
        try:
            s = datetime.datetime.strptime(start_date, "%Y-%m-%d")
            e = (
                datetime.datetime.strptime(end_date, "%Y-%m-%d") + datetime.timedelta(days=1)
                if end_date else s + datetime.timedelta(days=1)
            )
            conditions.append("(start_datetime BETWEEN %s AND %s OR start_datetime IS NULL)")
            params.extend([s, e])
        except Exception:
            pass

    # Distance filter — prefer explicit miles; fall back to legacy drive-minutes
    if max_distance_miles is not None:
        conditions.append("(distance_miles <= %s OR distance_miles IS NULL)")
        params.append(float(max_distance_miles))
    elif max_drive_min is not None:
        conditions.append("(estimated_drive_minutes <= %s OR estimated_drive_minutes IS NULL)")
        params.append(int(max_drive_min))

    # Only show events from enabled sources (public view)
    if enabled_only:
        conditions.append("(es.enabled = TRUE OR es.enabled IS NULL)")

    # Client-selected source filter
    if source_keys:
        placeholders = ",".join(["%s"] * len(source_keys))
        conditions.append(f"e.source_key IN ({placeholders})")
        params.extend(source_keys)

    where = " AND ".join(conditions)

    if sort == "closest":
        order = (
            "CASE WHEN distance_miles IS NULL THEN 1 ELSE 0 END, "
            "distance_miles ASC, start_datetime ASC"
        )
    else:
        order = (
            "CASE WHEN start_datetime IS NULL THEN 1 ELSE 0 END, "
            "start_datetime ASC, distance_miles ASC"
        )

    limit = max(1, min(int(limit), 500))
    offset = max(0, int(offset))
    params.extend([limit, offset])

    cur = conn.cursor(dictionary=True)
    cur.execute(
        f"""SELECT e.*, es.display_name, es.enabled AS source_enabled
            FROM external_events e
            LEFT JOIN event_sources es ON e.source_key = es.source_key
            WHERE {where} ORDER BY {order} LIMIT %s OFFSET %s""",
        params
    )
    results = cur.fetchall()
    cur.close()

    for r in results:
        for f in ("start_datetime", "end_datetime", "first_seen_at", "last_seen_at",
                  "created_at", "updated_at"):
            if r.get(f) and isinstance(r[f], datetime.datetime):
                r[f] = r[f].isoformat()

    return results


# ── DB migration ──────────────────────────────────────────────────────────────

_MIGRATION_SQL = """
CREATE TABLE IF NOT EXISTS event_sources (
    id               INT AUTO_INCREMENT PRIMARY KEY,
    source_key       VARCHAR(64) NOT NULL UNIQUE,
    display_name     VARCHAR(128) NOT NULL,
    enabled          BOOLEAN DEFAULT TRUE,
    last_success_at  DATETIME,
    last_attempt_at  DATETIME,
    last_error       TEXT,
    created_at       TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    updated_at       TIMESTAMP DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP
);

CREATE TABLE IF NOT EXISTS external_events (
    id                      INT AUTO_INCREMENT PRIMARY KEY,
    source_key              VARCHAR(64) NOT NULL,
    source_event_id         VARCHAR(255),
    source_url              VARCHAR(1024),
    official_url            VARCHAR(1024),
    title                   VARCHAR(512) NOT NULL,
    description_short       TEXT,
    start_datetime          DATETIME,
    end_datetime            DATETIME,
    date_label              VARCHAR(128),
    venue_name              VARCHAR(255),
    address                 VARCHAR(255),
    city                    VARCHAR(128),
    state                   CHAR(2),
    postal_code             VARCHAR(10),
    latitude                DECIMAL(10,7),
    longitude               DECIMAL(10,7),
    category                VARCHAR(64),
    image_url               VARCHAR(1024),
    admission               VARCHAR(255),
    distance_miles          DECIMAL(6,2),
    estimated_drive_minutes INT,
    direction_bucket        VARCHAR(16),
    normalized_fingerprint  VARCHAR(64),
    raw_source_json         MEDIUMTEXT,
    hidden                  BOOLEAN DEFAULT FALSE,
    saved                   BOOLEAN DEFAULT FALSE,
    first_seen_at           TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    last_seen_at            TIMESTAMP DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
    created_at              TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    updated_at              TIMESTAMP DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
    INDEX idx_source        (source_key),
    INDEX idx_fingerprint   (normalized_fingerprint),
    INDEX idx_start         (start_datetime),
    INDEX idx_hidden        (hidden),
    INDEX idx_saved         (saved)
);
"""


def ensure_tables(conn):
    """Create events tables if they don't exist. Idempotent."""
    cur = conn.cursor()
    for stmt in _MIGRATION_SQL.split(";"):
        stmt = stmt.strip()
        if stmt:
            try:
                cur.execute(stmt)
            except Exception as e:
                print(f"[events] migration stmt error: {e}")
    conn.commit()
    cur.close()
    print("[events] Tables ready.")
