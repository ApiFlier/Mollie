"""
External events core module: refresh, dedupe, distance, cache, query.
"""
import hashlib
import math
import os
import datetime
import threading

def _clamp_coverage_days(val, default=60, min_val=7, max_val=180):
    """Parse and clamp a coverage_days value. Returns default for missing/invalid."""
    if val is None or val == "":
        return default
    try:
        v = int(val)
    except (ValueError, TypeError):
        return default
    return max(min_val, min(max_val, v))


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


def _parse_int_env(name, default, min_val=None, max_val=None):
    """Return int from env var, falling back to default on blank/invalid/out-of-range.
    default may be None; None is returned for missing/blank/invalid values when default=None."""
    raw = os.environ.get(name, "").strip()
    if not raw:
        return default
    try:
        val = int(raw)
    except (ValueError, TypeError):
        print(f"[events] WARNING: {name}={raw!r} is not a valid int; using default {default}")
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

# Stale event retention.
# Unsaved external_events with a start/end older than this many days are
# deleted automatically after each successful source refresh.
# Set EVENT_CACHE_RETENTION_DAYS in .env to override (1–365, default 14).
EVENT_CACHE_RETENTION_DAYS = _parse_int_env(
    "EVENT_CACHE_RETENTION_DAYS", default=14, min_val=1, max_val=365
)

# Saved event retention.
# None (default) means saved events are kept indefinitely.
# Set SAVED_EVENT_RETENTION_DAYS in .env to a number of days to enable
# automatic cleanup of saved events that are older than that threshold.
_SAVED_RETENTION_DAYS = _parse_int_env(
    "SAVED_EVENT_RETENTION_DAYS", default=None, min_val=1, max_val=3650
)

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

def make_fingerprint(source_key, source_event_id=None, start_datetime=None,
                     title=None, venue_or_url=None):
    """Return an MD5 occurrence fingerprint for an external event.

    Identity priority:
      A. source_key + source_event_id + full start_datetime  (preferred — all adapters have IDs)
      B. source_key + title + full start_datetime + venue_or_url  (no stable upstream ID)
      C. title + date-only + venue_or_url  (legacy last resort — should not reach)

    Including the full start_datetime (HH:MM:SS) ensures same-title/same-venue
    events at different times on the same day are treated as distinct occurrences.
    Including source_key ensures events from different sources never collide.
    """
    _skey = (str(source_key) if source_key else "").lower().strip()
    _eid  = (str(source_event_id) if source_event_id is not None else "").strip()
    _dt   = (str(start_datetime) if start_datetime is not None else "")[:19]
    _ttl  = (str(title) if title else "").lower().strip()
    _vnu  = (str(venue_or_url) if venue_or_url else "").lower().strip()

    if _skey and _eid and _dt:
        # Path A: stable occurrence ID from upstream source
        parts = [_skey, _eid, _dt]
    elif _skey and _ttl and _dt:
        # Path B: no upstream ID — use content-based identity
        parts = [_skey, _ttl, _dt, _vnu]
    else:
        # Path C: legacy fallback; date-only, no source_key
        parts = [_ttl, _dt[:10], _vnu]

    return hashlib.md5("|".join(parts).encode()).hexdigest()


def make_series_key(source_key, title):
    """Return a stable key grouping recurring events by source + title.

    Intentionally excludes date/time so all occurrences of a recurring event
    share the same series_key. NOT used for deduplication — stored only on
    external_events for future 'Mollie has seen this kind of event before' queries.
    """
    parts = [
        (str(source_key) if source_key else "").lower().strip(),
        (str(title) if title else "").lower().strip(),
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


def _apply_user_state(conn, fingerprint):
    """Restore saved/hidden from external_event_user_state after an upsert.

    Called after every insert or update so that Mollie's saved/hidden choices
    survive cache refresh cycles without the source overwriting them.
    """
    if not fingerprint:
        return
    cur = conn.cursor(dictionary=True)
    cur.execute(
        "SELECT saved, hidden FROM external_event_user_state"
        " WHERE normalized_fingerprint = %s",
        (fingerprint,)
    )
    state = cur.fetchone()
    cur.close()
    if not state:
        return
    cur = conn.cursor()
    cur.execute(
        "UPDATE external_events SET saved=%s, hidden=%s"
        " WHERE normalized_fingerprint=%s",
        (bool(state["saved"]), bool(state["hidden"]), fingerprint)
    )
    cur.close()


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

    _apply_user_state(conn, fp)


def _do_update(conn, event_id, ev):
    cur = conn.cursor()
    cur.execute(
        """UPDATE external_events SET
             source_url=%s, official_url=%s, title=%s, description_short=%s,
             start_datetime=%s, end_datetime=%s, date_label=%s,
             venue_name=%s, address=%s, city=%s, state=%s, postal_code=%s,
             latitude=%s, longitude=%s, category=%s, image_url=%s, admission=%s,
             distance_miles=%s, estimated_drive_minutes=%s,
             series_key=%s, raw_source_json=%s,
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
            ev.get("series_key"), ev.get("raw_source_json"),
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
             normalized_fingerprint, series_key, raw_source_json
           ) VALUES (
             %s,%s,%s,%s, %s,%s,%s,%s,%s, %s,%s,%s,%s,%s,
             %s,%s,%s,%s,%s, %s,%s, %s,%s,%s
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
            ev.get("normalized_fingerprint"), ev.get("series_key"),
            ev.get("raw_source_json"),
        )
    )
    cur.close()


# ── Deduplication ────────────────────────────────────────────────────────────

def _dedupe_external_events(conn):
    """Resolve any duplicate external_events rows that share a normalized_fingerprint.

    The new occurrence-safe fingerprint (source_key + source_event_id + start_datetime)
    makes true duplicates rare. This function handles any that exist (e.g., from
    a pre-migration schema or a source that returned the same event twice).

    Safety: if rows share a fingerprint but have different start_datetimes, they
    are NOT collapsed — they are distinct occurrences that happened to collide
    (should not occur with the new fingerprint algorithm, but guarded defensively).

    For genuine duplicates: keep the richest/user-touched row, merge saved/hidden
    flags from all rows before deleting the others.
    """
    cur = conn.cursor(dictionary=True)
    cur.execute(
        "SELECT normalized_fingerprint, COUNT(*) AS cnt"
        " FROM external_events"
        " WHERE normalized_fingerprint IS NOT NULL"
        " GROUP BY normalized_fingerprint HAVING cnt > 1"
    )
    dup_groups = cur.fetchall()
    cur.close()

    if not dup_groups:
        return 0

    total_deleted = 0
    for group in dup_groups:
        fp = group["normalized_fingerprint"]
        cur = conn.cursor(dictionary=True)
        cur.execute(
            "SELECT id, saved, hidden, start_datetime, source_url, latitude,"
            "       venue_name, admission, category, updated_at"
            " FROM external_events"
            " WHERE normalized_fingerprint = %s ORDER BY id",
            (fp,)
        )
        rows = cur.fetchall()
        cur.close()
        if len(rows) <= 1:
            continue

        # Safety: rows with different start_datetimes are distinct occurrences —
        # do NOT collapse them even if they share a fingerprint (defensive guard).
        datetimes = {str(r.get("start_datetime") or "") for r in rows}
        if len(datetimes) > 1:
            print(
                f"[events] dedup SKIP: fingerprint {fp!r} has rows with "
                f"different start_datetimes {datetimes!r} — keeping all"
            )
            continue

        def _row_score(r):
            ts = r.get("updated_at")
            ts_val = ts.timestamp() if hasattr(ts, "timestamp") else 0
            return (
                bool(r.get("saved"))       * 100000 +
                bool(r.get("hidden"))      * 10000 +
                bool(r.get("source_url"))  * 1000 +
                bool(r.get("latitude"))    * 100 +
                bool(r.get("venue_name"))  * 10 +
                bool(r.get("admission"))   * 5 +
                bool(r.get("category"))    * 2 +
                min(int(ts_val), 9999999)
            )

        rows_sorted = sorted(rows, key=_row_score, reverse=True)
        keep = rows_sorted[0]
        delete_ids = [r["id"] for r in rows_sorted[1:]]

        # Merge saved/hidden from all rows into kept row
        any_saved  = any(r.get("saved")  for r in rows)
        any_hidden = any(r.get("hidden") for r in rows)

        cur2 = conn.cursor()
        if bool(any_saved) != bool(keep.get("saved")) or \
                bool(any_hidden) != bool(keep.get("hidden")):
            cur2.execute(
                "UPDATE external_events SET saved=%s, hidden=%s WHERE id=%s",
                (bool(any_saved), bool(any_hidden), keep["id"])
            )

        placeholders = ",".join(["%s"] * len(delete_ids))
        cur2.execute(
            f"DELETE FROM external_events WHERE id IN ({placeholders})",
            delete_ids
        )
        total_deleted += len(delete_ids)
        conn.commit()
        cur2.close()

    if total_deleted:
        print(f"[events] deduplication: removed {total_deleted} duplicate"
              f" external_events row(s)")
    return total_deleted


# ── Stale event cleanup ───────────────────────────────────────────────────────

def _purge_stale_for_source(conn, source_key,
                             retention_days=None,
                             saved_retention_days=None):
    """Delete old external_events rows for one source after a successful refresh.

    Deletes rows that Mollie has NOT interacted with (not saved, not hidden,
    not user_touched) where the event ended more than retention_days ago.
    Uses COALESCE(end_datetime, start_datetime) so multi-day events are not
    removed before they finish. Rows with no datetime are left alone.

    Preservation rules:
      - saved=TRUE rows are kept indefinitely (unless saved_retention_days is set)
      - hidden=TRUE rows are kept (Mollie explicitly chose to hide them)
      - user_touched=TRUE in external_event_user_state keeps the row

    saved_retention_days: if None (default), saved/hidden events are kept forever.
    """
    if retention_days is None:
        retention_days = EVENT_CACHE_RETENTION_DAYS

    cutoff = datetime.datetime.utcnow() - datetime.timedelta(days=retention_days)
    cur = conn.cursor()

    # Delete untouched stale rows: not saved, not hidden, no user_state entry
    cur.execute(
        "DELETE e FROM external_events e"
        " LEFT JOIN external_event_user_state us"
        "   ON e.normalized_fingerprint = us.normalized_fingerprint"
        " WHERE e.source_key = %s"
        "   AND e.saved = FALSE"
        "   AND e.hidden = FALSE"
        "   AND (us.normalized_fingerprint IS NULL OR us.user_touched = FALSE)"
        "   AND COALESCE(e.end_datetime, e.start_datetime) IS NOT NULL"
        "   AND COALESCE(e.end_datetime, e.start_datetime) < %s",
        (source_key, cutoff)
    )
    unsaved_removed = cur.rowcount

    saved_removed = 0
    if saved_retention_days is not None:
        saved_cutoff = (datetime.datetime.utcnow()
                        - datetime.timedelta(days=saved_retention_days))
        # Only delete saved/hidden rows with no active user_state entry
        cur.execute(
            "DELETE e FROM external_events e"
            " LEFT JOIN external_event_user_state us"
            "   ON e.normalized_fingerprint = us.normalized_fingerprint"
            " WHERE e.source_key = %s"
            "   AND (e.saved = TRUE OR e.hidden = TRUE)"
            "   AND (us.normalized_fingerprint IS NULL OR us.user_touched = FALSE)"
            "   AND COALESCE(e.end_datetime, e.start_datetime) IS NOT NULL"
            "   AND COALESCE(e.end_datetime, e.start_datetime) < %s",
            (source_key, saved_cutoff)
        )
        saved_removed = cur.rowcount

    conn.commit()
    cur.close()

    total = unsaved_removed + saved_removed
    if total:
        parts = [f"{unsaved_removed} stale untouched"]
        if saved_removed:
            parts.append(f"{saved_removed} stale saved/hidden")
        print(f"[events] {source_key}: purged {', '.join(parts)} event(s)")
    return total


# ── Refresh ───────────────────────────────────────────────────────────────────

def refresh_source(conn, source_key):
    """Fetch and upsert events for one source.

    Returns count of events upserted. Stale cleanup runs only after a
    successful fetch so a failed source does not lose its cached data.
    """
    adapter = _ADAPTERS.get(source_key)
    if not adapter:
        raise ValueError(f"Unknown source: {source_key}")

    _ensure_source(conn, source_key, adapter.display_name)
    coverage_days = get_source_coverage_days(conn, source_key)

    try:
        events = adapter.fetch(coverage_days=coverage_days)
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

    # Stale cleanup runs only after a successful fetch so a failed source
    # does not lose its cached rows before they can be refreshed.
    stale_removed = _purge_stale_for_source(
        conn, source_key,
        retention_days=EVENT_CACHE_RETENTION_DAYS,
        saved_retention_days=_SAVED_RETENTION_DAYS,
    )

    print(f"[events] {source_key}: {count} upserted, {stale_removed} stale removed")
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


# ── Price normalization ───────────────────────────────────────────────────────

def _parse_admission_price(admission):
    """Parse an admission string into normalized price fields.

    Returns dict with keys: is_free (bool), price_min (float|None),
    price_max (float|None), price_status ('free'|'listed'|'unknown').
    """
    if admission is None:
        return {"is_free": False, "price_min": None, "price_max": None, "price_status": "unknown"}
    adm = str(admission).strip()
    if adm.lower() == "free":
        return {"is_free": True, "price_min": 0.0, "price_max": 0.0, "price_status": "free"}
    clean = adm.lstrip("$")
    if "–" in clean:  # en dash — range like "$10–$20"
        parts = clean.split("–", 1)
        try:
            lo = float(parts[0].strip().lstrip("$"))
            hi = float(parts[1].strip().lstrip("$"))
            return {"is_free": False, "price_min": lo, "price_max": hi, "price_status": "listed"}
        except (ValueError, TypeError):
            pass
    else:
        try:
            val = float(clean)
            return {"is_free": False, "price_min": val, "price_max": val, "price_status": "listed"}
        except (ValueError, TypeError):
            pass
    return {"is_free": False, "price_min": None, "price_max": None, "price_status": "listed"}


def _enrich_event(r):
    """Add normalized price fields to a DB row dict in-place."""
    p = _parse_admission_price(r.get("admission"))
    r["is_free"] = p["is_free"]
    r["price_min"] = p["price_min"]
    r["price_max"] = p["price_max"]
    r["price_status"] = p["price_status"]
    return r


def _filter_by_price(events, price_filter, max_price=None):
    """In-memory price filter. price_filter: 'any'|'free'|'listed'|'unknown'|'max'."""
    if not price_filter or price_filter == "any":
        return events
    result = []
    for ev in events:
        status = ev.get("price_status", "unknown")
        if price_filter == "free":
            if ev.get("is_free"):
                result.append(ev)
        elif price_filter == "listed":
            if status == "listed":
                result.append(ev)
        elif price_filter == "unknown":
            if status == "unknown":
                result.append(ev)
        elif price_filter == "max" and max_price is not None:
            pmin = ev.get("price_min")
            if ev.get("is_free") or (status == "listed" and pmin is not None and pmin <= max_price):
                result.append(ev)
    return result


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
            "SELECT source_key, display_name, enabled, coverage_days"
            " FROM event_sources WHERE enabled = TRUE ORDER BY source_key"
        )
    else:
        cur.execute(
            "SELECT source_key, display_name, enabled, coverage_days"
            " FROM event_sources ORDER BY source_key"
        )
    rows = cur.fetchall()
    cur.close()
    for r in rows:
        r["coverage_days"] = _clamp_coverage_days(r.get("coverage_days"))
    return rows


def get_source_coverage_days(conn, source_key):
    """Return the configured coverage_days for a source, clamped to valid range."""
    cur = conn.cursor(dictionary=True)
    cur.execute(
        "SELECT coverage_days FROM event_sources WHERE source_key = %s", (source_key,)
    )
    row = cur.fetchone()
    cur.close()
    if not row or row.get("coverage_days") is None:
        return 60
    return _clamp_coverage_days(row["coverage_days"])


def get_events(conn, filter_type=None, sort=None, saved_only=False,
               max_drive_min=None, max_distance_miles=None,
               date_filter=None, start_date=None, end_date=None,
               source_keys=None, enabled_only=True,
               limit=100, offset=0,
               price_filter=None, max_price=None):
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
        _enrich_event(r)

    if price_filter and price_filter != "any":
        results = _filter_by_price(results, price_filter, max_price)

    return results


# ── DB migration ──────────────────────────────────────────────────────────────

def _migrate_to_occurrence_fingerprint(conn):
    """One-time migration: preserve user state then clear cache for repopulation.

    The new fingerprint algorithm (source_key + source_event_id + start_datetime)
    produces completely different hashes from the old algorithm (title + date_only
    + venue_or_url). Existing rows in external_events have stale fingerprints that
    will never match refreshed data from adapters.

    Steps:
    1. Migrate any saved/hidden rows to external_event_user_state with new
       fingerprints computed from stored source_key + source_event_id + start_datetime.
    2. Drop the old UNIQUE constraint (built on old fingerprints).
    3. TRUNCATE external_events — it is runtime cache, repopulated immediately
       because all sources will be stale after truncation.
    4. Re-add the UNIQUE constraint on the fresh table.
    """
    print("[events] Running one-time migration to occurrence-safe fingerprints...")

    # Step 1: Migrate saved/hidden state to user_state with new fingerprints
    cur = conn.cursor(dictionary=True)
    cur.execute(
        "SELECT source_key, source_event_id, start_datetime,"
        "       title, venue_name, source_url, saved, hidden"
        " FROM external_events WHERE saved = TRUE OR hidden = TRUE"
    )
    user_rows = cur.fetchall()
    cur.close()

    migrated = 0
    for row in user_rows:
        new_fp = make_fingerprint(
            row["source_key"],
            row.get("source_event_id"),
            str(row["start_datetime"]) if row["start_datetime"] else None,
            row.get("title"),
            row.get("venue_name") or row.get("source_url"),
        )
        cur = conn.cursor()
        cur.execute(
            """INSERT INTO external_event_user_state
               (normalized_fingerprint, saved, hidden, user_touched)
               VALUES (%s, %s, %s, TRUE)
               ON DUPLICATE KEY UPDATE
               saved = saved OR VALUES(saved),
               hidden = hidden OR VALUES(hidden),
               user_touched = TRUE,
               last_touched_at = NOW()""",
            (new_fp, bool(row["saved"]), bool(row["hidden"]))
        )
        cur.close()
        migrated += 1

    conn.commit()

    # Step 2: Drop old UNIQUE constraint (may not exist — OK if it fails)
    try:
        cur = conn.cursor()
        cur.execute("ALTER TABLE external_events DROP INDEX uniq_fingerprint")
        conn.commit()
        cur.close()
    except Exception:
        pass

    # Step 3: Truncate external_events cache — will auto-repopulate on next refresh
    cur = conn.cursor()
    cur.execute("TRUNCATE TABLE external_events")
    conn.commit()
    cur.close()

    # Step 4: Re-add UNIQUE constraint on fresh table
    try:
        cur = conn.cursor()
        cur.execute(
            "ALTER TABLE external_events"
            " ADD UNIQUE KEY uniq_fingerprint (normalized_fingerprint)"
        )
        conn.commit()
        cur.close()
    except Exception:
        pass

    print(
        f"[events] Migration complete: {migrated} user-state row(s) preserved;"
        " event cache cleared and will repopulate on next refresh."
    )


_MIGRATION_SQL = """
CREATE TABLE IF NOT EXISTS event_sources (
    id               INT AUTO_INCREMENT PRIMARY KEY,
    source_key       VARCHAR(64) NOT NULL UNIQUE,
    display_name     VARCHAR(128) NOT NULL,
    enabled          BOOLEAN DEFAULT TRUE,
    coverage_days    INT NOT NULL DEFAULT 60,
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
    series_key              VARCHAR(64),
    raw_source_json         MEDIUMTEXT,
    hidden                  BOOLEAN DEFAULT FALSE,
    saved                   BOOLEAN DEFAULT FALSE,
    first_seen_at           TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    last_seen_at            TIMESTAMP DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
    created_at              TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    updated_at              TIMESTAMP DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
    INDEX idx_source        (source_key),
    INDEX idx_fingerprint   (normalized_fingerprint),
    INDEX idx_series        (series_key),
    INDEX idx_start         (start_datetime),
    INDEX idx_hidden        (hidden),
    INDEX idx_saved         (saved)
);

CREATE TABLE IF NOT EXISTS external_event_user_state (
    normalized_fingerprint  VARCHAR(64) NOT NULL,
    saved                   BOOLEAN NOT NULL DEFAULT FALSE,
    hidden                  BOOLEAN NOT NULL DEFAULT FALSE,
    user_touched            BOOLEAN NOT NULL DEFAULT FALSE,
    first_touched_at        TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
    last_touched_at         TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
    note                    VARCHAR(500) NULL,
    PRIMARY KEY (normalized_fingerprint)
);

CREATE TABLE IF NOT EXISTS _event_migrations (
    migration_key  VARCHAR(64) NOT NULL,
    applied_at     TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
    PRIMARY KEY (migration_key)
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

    # Safe backfill: add coverage_days column to existing installs.
    try:
        cur.execute(
            "ALTER TABLE event_sources ADD COLUMN coverage_days INT NOT NULL DEFAULT 60"
        )
        conn.commit()
        print("[events] Added coverage_days column to event_sources.")
    except Exception:
        pass  # Column already exists — expected on re-run.

    # Safe backfill: add series_key column to existing external_events installs.
    try:
        cur.execute(
            "ALTER TABLE external_events ADD COLUMN series_key VARCHAR(64) NULL,"
            " ADD INDEX idx_series (series_key)"
        )
        conn.commit()
        print("[events] Added series_key column to external_events.")
    except Exception:
        pass  # Column already exists — expected on re-run.

    # One-time migration: update old default coverage_days=60 to the new default 60.
    # Runs once per install; does NOT touch custom non-30 values (45, 90, 120, etc.).
    cur.execute(
        "SELECT migration_key FROM _event_migrations"
        " WHERE migration_key = 'event_source_coverage_default_60_v1'"
    )
    if not cur.fetchone():
        try:
            cur.execute(
                "ALTER TABLE event_sources"
                " MODIFY COLUMN coverage_days INT NOT NULL DEFAULT 60"
            )
            cur.execute(
                "UPDATE event_sources SET coverage_days = 60 WHERE coverage_days = 30"
            )
            conn.commit()
            cur.execute(
                "INSERT IGNORE INTO _event_migrations (migration_key)"
                " VALUES ('event_source_coverage_default_60_v1')"
            )
            conn.commit()
            print("[events] Migrated coverage_days default 30→60 for existing sources.")
        except Exception as e:
            print(f"[events] coverage_days migration warning: {e}")

    # One-time migration to occurrence-safe fingerprints (occurrence_fingerprint_v1).
    # Tracked in _event_migrations so it runs exactly once per install.
    cur.execute(
        "SELECT migration_key FROM _event_migrations"
        " WHERE migration_key = 'occurrence_fingerprint_v1'"
    )
    if not cur.fetchone():
        _migrate_to_occurrence_fingerprint(conn)
        cur.execute(
            "INSERT IGNORE INTO _event_migrations (migration_key) VALUES ('occurrence_fingerprint_v1')"
        )
        conn.commit()

    # After migration the table is fresh; add UNIQUE constraint if not present.
    try:
        cur.execute(
            "ALTER TABLE external_events"
            " ADD UNIQUE KEY uniq_fingerprint (normalized_fingerprint)"
        )
        conn.commit()
        print("[events] Added UNIQUE constraint on external_events.normalized_fingerprint.")
    except Exception:
        pass  # Already exists — expected on re-run.

    # Pre-seed all registered adapters so they appear in admin/source filters
    # before their first refresh. ON DUPLICATE KEY UPDATE is a safe no-op.
    for key, adapter in _ADAPTERS.items():
        try:
            cur.execute(
                "INSERT INTO event_sources (source_key, display_name)"
                " VALUES (%s, %s)"
                " ON DUPLICATE KEY UPDATE display_name = %s",
                (key, adapter.display_name, adapter.display_name)
            )
        except Exception as e:
            print(f"[events] could not pre-seed source {key!r}: {e}")
    conn.commit()
    cur.close()
    print("[events] Tables ready.")
