import datetime
import json
import re
from zoneinfo import ZoneInfo

REGIONAL_TZ = ZoneInfo("America/New_York")


class FetchResult(list):
    """List-compatible adapter result carrying completeness information."""
    def __init__(self, values=(), complete=True, error=None, warnings=None):
        super().__init__(values)
        self.complete = bool(complete)
        self.error = str(error) if error else None
        self.warnings = list(warnings or [])


def utc_naive_string(value, source_tz=REGIONAL_TZ, epoch=False):
    if value in (None, ""):
        return None
    try:
        if epoch:
            dt = datetime.datetime.fromtimestamp(float(value), datetime.timezone.utc)
        elif isinstance(value, datetime.datetime):
            dt = value
        else:
            text = str(value).strip()
            if text.endswith("Z"):
                text = text[:-1] + "+00:00"
            dt = datetime.datetime.fromisoformat(text)
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=source_tz)
        return dt.astimezone(datetime.timezone.utc).replace(tzinfo=None).strftime("%Y-%m-%d %H:%M:%S")
    except (ValueError, TypeError, OverflowError):
        return None


def wall_clock_epoch_to_utc(value, source_tz=REGIONAL_TZ):
    """Decode EventON's UTC-shaped epoch as local wall-clock components."""
    try:
        wall = datetime.datetime.fromtimestamp(float(value), datetime.timezone.utc).replace(tzinfo=None)
        return wall.replace(tzinfo=source_tz).astimezone(datetime.timezone.utc).replace(tzinfo=None).strftime("%Y-%m-%d %H:%M:%S")
    except (ValueError, TypeError, OverflowError):
        return None


def strip_html(value, limit=None):
    if not value:
        return None
    text = re.sub(r"<[^>]+>", " ", str(value))
    text = " ".join(text.split())
    if limit and len(text) > limit:
        text = text[:limit - 1].rstrip() + "…"
    return text or None


def json_text(value):
    return json.dumps(value, default=str, ensure_ascii=False)


def first_url(value):
    if isinstance(value, str) and value.startswith(("http://", "https://")):
        return value
    return None
