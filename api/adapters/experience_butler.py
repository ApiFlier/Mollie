import os
import datetime

from adapters.algolia_events import AlgoliaEventsAdapter, parse_address_array
from adapters.utils import json_text, strip_html, utc_naive_string
import events as _events


class ExperienceButler(AlgoliaEventsAdapter):
    source_key = "experience_butler"
    display_name = "Experience Butler County"
    homepage_url = "https://www.experiencebutler.com/events/"
    app_id = os.environ.get("EB_ALGOLIA_APP_ID", "EYQHJ2IY2M")
    api_key = os.environ.get("EB_ALGOLIA_API_KEY", "c6d5977cb5cd80c09abfd2a7e5d9e88b")
    index_name = os.environ.get("EB_ALGOLIA_INDEX", "prod-experience-butler-listings")
    endpoint = f"https://{app_id.lower()}-dsn.algolia.net/1/indexes/*/queries"
    queries = (str(datetime.date.today().year), "event", "festival")

    def normalize(self, hit):
        venue, address, city, state, postal = parse_address_array(hit.get("address"))
        start = utc_naive_string(hit.get("startDate"), epoch=True)
        end = utc_naive_string(hit.get("endDate"), epoch=True)
        object_id = str(hit.get("objectID") or hit.get("id") or "")
        title = strip_html(hit.get("title")) or ""
        uri = str(hit.get("uri") or "").strip("/")
        source_url = f"https://www.experiencebutler.com/events/{uri}/" if uri else self.homepage_url
        geoloc = hit.get("_geoloc") or {}
        categories = hit.get("eventCategories") or []
        category = categories[0] if categories else None
        if isinstance(category, dict):
            category = category.get("title") or category.get("name") or category.get("label")
        series_basis = hit.get("distinctField") or hit.get("id")
        series_key = _events.make_series_key(self.source_key, str(series_basis)) if series_basis else _events.make_series_key(self.source_key, title)
        return {
            "source_key": self.source_key, "source_event_id": object_id,
            "source_url": source_url, "official_url": hit.get("website") or source_url,
            "title": title, "description_short": strip_html(hit.get("content") or hit.get("snippet"), 300),
            "start_datetime": start, "end_datetime": end,
            "date_label": None, "venue_name": venue, "address": address,
            "city": city, "state": state, "postal_code": postal,
            "latitude": geoloc.get("lat"), "longitude": geoloc.get("lng"),
            "category": category, "image_url": hit.get("primaryImageUrl"), "admission": None,
            "normalized_fingerprint": _events.make_fingerprint(self.source_key, object_id, start, title, venue or source_url),
            "series_key": series_key, "raw_source_json": json_text(hit),
        }
