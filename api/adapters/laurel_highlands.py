import json
import os
import requests
from adapters.simpleview import SimpleviewEventsAdapter


class LaurelHighlands(SimpleviewEventsAdapter):
    source_key = "laurel_highlands"
    display_name = "Laurel Highlands"
    homepage_url = "https://www.golaurelhighlands.com/events/"
    base_url = "https://www.golaurelhighlands.com"
    token = os.environ.get("LAUREL_SIMPLEVIEW_TOKEN", "3e0c7cc3125bd4c48ede37f22b2f2f9c")
    category_ids = ("87","60","82","61","83","84","70","79","73","62","71","63","64","77","80","81","65","66","67","68","85","72","69","86","74")
    category_map = {"61":"Art Exhibits & Museums","62":"Family Fun","64":"Food and Drink","65":"Heritage","67":"Music & Dance","68":"Outdoor","72":"Summer Concerts / Live Music","79":"Dining Specials","81":"Health & Wellness","82":"Art Classes","87":"America250PA"}

    def normalize(self, doc):
        event = super().normalize(doc)
        if event:
            # This site's `region` is a county name (for example WESTMORELAND),
            # not a postal state code. Laurel Highlands records are in PA.
            event["state"] = "PA"
        return event

    _browser_headers = {
        "User-Agent": "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 Chrome/127.0.0.0 Safari/537.36",
        "Accept-Language": "en-US,en;q=0.9",
    }

    def _query(self, coverage_days, skip, include_admission=True, limit=None):
        query = super()._query(coverage_days, skip, False, limit)
        categories = query["filter"].pop("categories.catId")
        query["filter"].update({"active": True, "$and": [{"categories.catId": categories}]})
        fields = query["options"]["fields"]
        fields.pop("listing", None)
        for key in ("primary_category", "recid", "acctid", "city", "region", "title", "url"):
            fields[f"listing.{key}"] = 1
        query["options"]["hooks"] = []
        return query

    def _get_page(self, coverage_days, skip, include_admission=True, limit=None):
        endpoint = self.base_url + "/includes/rest_v2/plugins_events_events_by_date/find/"
        response = self._session.get(
            endpoint,
            params={
                "json": json.dumps(self._query(coverage_days, skip, False, limit), separators=(",", ":")),
                "token": self._runtime_token,
            },
            timeout=25,
            headers={**self._browser_headers, "Accept": "application/json, text/plain, */*", "Referer": self.homepage_url},
        )
        response.raise_for_status()
        return response.json()

    def fetch(self, coverage_days=60):
        self._session = requests.Session()
        self._runtime_token = self.token
        try:
            # This mirrors the public site's documented tokenLoader flow. The
            # configured public token remains a fallback if bootstrap fails.
            self._session.get(
                self.homepage_url,
                headers={**self._browser_headers, "Accept": "text/html,application/xhtml+xml"},
                timeout=25,
            ).raise_for_status()
            token_response = self._session.get(
                self.base_url + "/plugins/core/get_simple_token/",
                headers={**self._browser_headers, "Referer": self.homepage_url},
                timeout=20,
            )
            token_response.raise_for_status()
            published = token_response.text.strip()
            if published:
                self._runtime_token = published
        except Exception as exc:
            print(f"[laurel_highlands] frontend token bootstrap failed; using configured fallback: {exc}")
        try:
            return super().fetch(coverage_days)
        finally:
            self._session.close()
