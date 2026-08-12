import datetime
import html
import json
import re
import requests
from urllib.parse import urlencode

from adapters.base import BaseAdapter
from adapters.utils import FetchResult, strip_html, utc_naive_string
import events as _events


class AlgoliaEventsAdapter(BaseAdapter):
    app_id = None
    api_key = None
    index_name = None
    endpoint = None
    queries = ("",)
    hits_per_page = 100
    max_pages = 50
    attributes = None

    def normalize(self, hit):
        raise NotImplementedError

    def is_event(self, hit):
        return hit.get("typeHandle") == "event" or hit.get("sectionHandle") == "events"

    def _request(self, query, page):
        headers = {
            "X-Algolia-Application-Id": self.app_id,
            "X-Algolia-API-Key": self.api_key,
            "Content-Type": "application/json",
        }
        params = {"query": query, "hitsPerPage": self.hits_per_page, "page": page}
        if self.attributes:
            params["attributesToRetrieve"] = self.attributes
        if self.endpoint.endswith("/queries"):
            body = {"requests": [{"indexName": self.index_name, "params": urlencode(params, doseq=True)}]}
            response = requests.post(self.endpoint, headers=headers, json=body, timeout=20)
            response.raise_for_status()
            data = response.json()
            return (data.get("results") or [{}])[0]
        response = requests.post(self.endpoint, headers=headers, json=params, timeout=20)
        response.raise_for_status()
        return response.json()

    def fetch(self, coverage_days=60):
        output, seen = [], set()
        cutoff = datetime.datetime.utcnow() + datetime.timedelta(days=max(1, int(coverage_days or 60)))
        for query in self.queries:
            page = 0
            while page < self.max_pages:
                try:
                    data = self._request(query, page)
                except Exception as exc:
                    return FetchResult(output, complete=False, error=f"query={query!r} page={page}: {exc}")
                hits = data.get("hits") or []
                for hit in hits:
                    if not self.is_event(hit) or hit.get("online_only") is True or hit.get("isVirtual") is True:
                        continue
                    normalized = self.normalize(hit)
                    start = normalized.get("start_datetime")
                    try:
                        if start and datetime.datetime.fromisoformat(start) > cutoff:
                            continue
                    except (TypeError, ValueError):
                        pass
                    occurrence = normalized.get("normalized_fingerprint")
                    if occurrence and occurrence not in seen:
                        seen.add(occurrence)
                        output.append(normalized)
                nb_pages = int(data.get("nbPages") or (1 if not hits else page + 1))
                page += 1
                if not hits or page >= nb_pages:
                    break
        return FetchResult(output)


def parse_address_array(values):
    values = values or []
    venue = values[0] if len(values) > 0 else None
    street = values[1] if len(values) > 1 else None
    tail = values[2] if len(values) > 2 else ""
    city = state = postal = None
    match = re.match(r"^\s*(.*?),\s*([A-Za-z ]+?)\s+(\d{5}(?:-\d{4})?)\s*$", tail or "")
    if match:
        city, state, postal = match.group(1), match.group(2), match.group(3)
        states = {"Pennsylvania": "PA", "Ohio": "OH", "West Virginia": "WV"}
        state = states.get(state, state[:2].upper())
    return venue, street, city or None, state or None, postal
