import datetime
import requests

from adapters.base import BaseAdapter
from adapters.utils import FetchResult, json_text, strip_html, utc_naive_string
import events as _events


class EvvntAdapter(BaseAdapter):
    api_base = "https://discovery.evvnt.com"
    publisher_id = None
    page_size = 50
    max_pages = 100

    @staticmethod
    def _reported_total(data):
        """Evvnt omits nbPages but exposes the result total in its facets."""
        for facet in data.get("rawFacets") or []:
            if not isinstance(facet, dict):
                continue
            if facet.get("name") == "country.name":
                values = facet.get("values") or facet.get("data") or []
                if isinstance(values, dict):
                    return sum(int(v or 0) for v in values.values())
                return sum(int(v.get("count") or 0) for v in values if isinstance(v, dict))
        return None

    @staticmethod
    def _url_from_links(links, priorities):
        links = links or {}
        if isinstance(links, list):
            pairs = []
            for item in links:
                if isinstance(item, dict):
                    pairs.append((item.get("name") or item.get("type") or "", item.get("url")))
        else:
            pairs = list(links.items())
        for wanted in priorities:
            for name, value in pairs:
                url = value.get("url") if isinstance(value, dict) else value
                if str(name).lower() == wanted.lower() and str(url).startswith("http"):
                    return url
        for _, value in pairs:
            url = value.get("url") if isinstance(value, dict) else value
            if str(url).startswith("http"):
                return url
        return None

    @staticmethod
    def _admission(ev):
        prices = ev.get("prices") or {}
        if not prices:
            text = " ".join(str(ev.get(k) or "") for k in ("summary", "description")).lower()
            return "Free" if "free admission" in text or "free event" in text else None
        values = []
        items = prices.values() if isinstance(prices, dict) else prices
        for value in items:
            text = str(value)
            import re
            match = re.search(r"(?:USD|\$)?\s*(\d+(?:\.\d+)?)", text, re.I)
            if match: values.append(float(match.group(1)))
        if not values: return None
        lo, hi = min(values), max(values)
        fmt = lambda n: str(int(n)) if n.is_integer() else f"{n:.2f}"
        if lo == 0 and hi == 0: return "Free"
        return f"${fmt(lo)}" if lo == hi else f"${fmt(lo)}–${fmt(hi)}"

    def normalize(self, ev):
        source_id = str(ev.get("source_id") or ev.get("source_id_s") or ev.get("objectID") or "")
        start = utc_naive_string(ev.get("start_time") or ev.get("start_date"))
        end = utc_naive_string(ev.get("end_time"))
        venue = ev.get("venue") or {}
        if not isinstance(venue, dict): venue = {"name": str(venue)}
        geoloc = ev.get("_geoloc") or {}
        if not isinstance(geoloc, dict): geoloc = {}
        lat = venue.get("latitude") or geoloc.get("lat")
        lng = venue.get("longitude") or geoloc.get("lng")
        original = self._url_from_links(ev.get("original_links"), ("Tickets", "Website"))
        redirect = self._url_from_links(ev.get("links"), ("Tickets", "Website"))
        source_url = ev.get("source_broadcast_url") or original or redirect
        official = original or redirect or source_url
        image = None
        images = ev.get("images") or []
        if isinstance(images, dict): images = [images]
        for entry in images:
            if not isinstance(entry, dict):
                continue
            for key in ("featured_webp", "featured", "list_thumb", "original"):
                block = entry.get(key) or {}
                if isinstance(block, str) and block.startswith("http"):
                    image = block; break
                if isinstance(block, dict) and block.get("url"):
                    image = block["url"]; break
            if image: break
        parent = ev.get("event_parent_id")
        title = strip_html(ev.get("title")) or ""
        return {
            "source_key": self.source_key, "source_event_id": source_id,
            "source_url": source_url, "official_url": official, "title": title,
            "description_short": strip_html(ev.get("summary") or ev.get("description"), 300),
            "start_datetime": start, "end_datetime": end, "date_label": None,
            "venue_name": venue.get("name") or venue.get("title"),
            "address": venue.get("address_1") or venue.get("address"),
            "city": venue.get("town") or venue.get("city"), "state": venue.get("region") or venue.get("state"),
            "postal_code": venue.get("postcode") or venue.get("postal_code"),
            "latitude": lat, "longitude": lng, "category": ev.get("category_name"),
            "image_url": image, "admission": self._admission(ev),
            "normalized_fingerprint": _events.make_fingerprint(self.source_key, source_id, start, title, source_url),
            "series_key": _events.make_series_key(self.source_key, str(parent) if parent else title),
            "raw_source_json": json_text(ev),
        }

    def fetch(self, coverage_days=60):
        output = []
        now = datetime.datetime.utcnow()
        cutoff = now + datetime.timedelta(days=max(1, int(coverage_days or 60)))
        for page in range(self.max_pages):
            try:
                response = requests.get(
                    f"{self.api_base}/api/publisher/{self.publisher_id}/home_page_events",
                    params={"hitsPerPage": self.page_size, "multipleEventInstances": "true", "page": page, "publisher_id": self.publisher_id},
                    timeout=25, headers={"Accept":"application/json", "User-Agent":"EventMapApp/1.0"})
                response.raise_for_status()
                data = response.json()
            except Exception as exc:
                return FetchResult(output, complete=False, error=f"page={page}: {exc}")
            batch = data.get("rawEvents") or []
            for ev in batch:
                if ev.get("online_only") is True: continue
                normalized = self.normalize(ev)
                start = normalized.get("start_datetime")
                try:
                    start_dt = datetime.datetime.fromisoformat(start) if start else None
                except (TypeError, ValueError):
                    start_dt = None
                if start_dt is None or (now - datetime.timedelta(days=1) <= start_dt <= cutoff):
                    output.append(normalized)
            total = self._reported_total(data)
            if (total is not None and (page + 1) * self.page_size >= total) or not batch or len(batch) < self.page_size:
                return FetchResult(output)
        return FetchResult(output, complete=False, error=f"reached {self.max_pages}-page safety limit")
