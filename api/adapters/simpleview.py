import datetime
import os
import requests

from adapters.base import BaseAdapter
from adapters.utils import FetchResult, REGIONAL_TZ, json_text, strip_html
import events as _events


class SimpleviewEventsAdapter(BaseAdapter):
    base_url = None
    token = None
    category_ids = ()
    category_map = {}
    page_size = 50
    max_pages = 50

    def _boundaries(self, coverage_days, now=None):
        now = now or datetime.datetime.now(REGIONAL_TZ)
        local_start = datetime.datetime.combine(now.date(), datetime.time.min, REGIONAL_TZ)
        local_end = local_start + datetime.timedelta(days=max(7, min(180, int(coverage_days))))
        def iso(dt):
            return dt.astimezone(datetime.timezone.utc).isoformat(timespec="milliseconds").replace("+00:00", "Z")
        return iso(local_start), iso(local_end)

    def _query(self, coverage_days, skip, include_admission=True, limit=None):
        start, end = self._boundaries(coverage_days)
        fields = {key: 1 for key in (
            "_id location date startDate endDate recurrence recurType latitude longitude "
            "media_raw recid title url categories accountId city region featured listing"
        ).split()}
        if include_admission:
            fields["admission"] = 1
        query = {
            "filter": {
                "date_range": {"start": {"$date": start}, "end": {"$date": end}},
                "categories.catId": {"$in": list(self.category_ids)},
            },
            "options": {
                "limit": limit or self.page_size, "skip": skip, "count": True,
                "castDocs": False, "fields": fields,
                "sort": {"date": 1, "rank": 1, "title_sort": 1},
            },
        }
        return query

    def _get_page(self, coverage_days, skip, include_admission=True, limit=None):
        endpoint = self.base_url.rstrip("/") + "/includes/rest_v2/plugins_events_events_by_date/find/"
        response = requests.get(endpoint, params={"json": json_text(self._query(coverage_days, skip, include_admission, limit)), "token": self.token}, timeout=25,
                                headers={"Accept": "application/json", "User-Agent": "Mozilla/5.0 (compatible; EventMapApp/1.0)", "Referer": self.homepage_url})
        response.raise_for_status()
        return response.json()

    def _local_occurrence_date(self, value):
        if value in (None, ""):
            return None
        try:
            if isinstance(value, dict):
                value = value.get("$date")
            if isinstance(value, (int, float)) or str(value).isdigit():
                dt = datetime.datetime.fromtimestamp(float(value) / (1000 if float(value) > 1e11 else 1), datetime.timezone.utc)
            else:
                text = str(value).replace("Z", "+00:00")
                dt = datetime.datetime.fromisoformat(text)
                if dt.tzinfo is None:
                    dt = dt.replace(tzinfo=datetime.timezone.utc)
            return dt.astimezone(REGIONAL_TZ).date()
        except Exception:
            return None

    def normalize(self, doc):
        local_date = self._local_occurrence_date(doc.get("date"))
        if not local_date:
            return None
        local_midnight = datetime.datetime.combine(local_date, datetime.time.min, REGIONAL_TZ)
        start = local_midnight.astimezone(datetime.timezone.utc).replace(tzinfo=None).strftime("%Y-%m-%d %H:%M:%S")
        recid = str(doc.get("recid") or doc.get("_id") or "")
        source_id = f"{recid}:{local_date.isoformat()}"
        title = strip_html(doc.get("title")) or ""
        listing = doc.get("listing") or {}
        media = doc.get("media_raw") or []
        if isinstance(media, dict): media = [media]
        image = listing.get("primary_image_url")
        for item in media:
            if isinstance(item, dict):
                image = item.get("resource_url") or item.get("url") or item.get("path")
                if image: break
        if not image:
            listing_media = listing.get("media") or []
            if listing_media:
                image = listing_media[0].get("mediaurl") or listing_media[0].get("mediathumburl")
        cats = doc.get("categories") or []
        cat_id = None
        if cats:
            first = cats[0]
            cat_id = str(first.get("catId") or first.get("id") or "") if isinstance(first, dict) else str(first)
        category = self.category_map.get(cat_id)
        if not category and cats and isinstance(cats[0], dict):
            category = cats[0].get("catName") or cats[0].get("title")
        path = doc.get("url") or ""
        source_url = self.base_url.rstrip("/") + (path if str(path).startswith("/") else "/" + str(path)) if path else self.homepage_url
        venue = doc.get("location") or listing.get("title")
        city = doc.get("city") or listing.get("city")
        state = listing.get("state") or doc.get("region") or listing.get("region")
        admission = doc.get("admission")
        if isinstance(admission, dict): admission = admission.get("value") or admission.get("label")
        return {
            "source_key": self.source_key, "source_event_id": source_id,
            "source_url": source_url, "official_url": source_url, "title": title,
            "description_short": strip_html(listing.get("description"), 300), "start_datetime": start, "end_datetime": None,
            "date_label": local_date.strftime("%a %b %-d"), "venue_name": venue,
            "address": listing.get("address1") or listing.get("address"), "city": city,
            "state": state, "postal_code": listing.get("zip") or listing.get("postalCode"),
            "latitude": doc.get("latitude"), "longitude": doc.get("longitude"),
            "category": category, "image_url": image, "admission": admission,
            "normalized_fingerprint": _events.make_fingerprint(self.source_key, source_id, start, title, venue or source_url),
            "series_key": _events.make_series_key(self.source_key, recid or title),
            "raw_source_json": json_text(doc),
        }

    def fetch(self, coverage_days=60):
        output, skip, pages = [], 0, 0
        include_admission, limit = True, self.page_size
        while pages < self.max_pages:
            try:
                data = self._get_page(coverage_days, skip, include_admission, limit)
            except Exception as exc:
                if include_admission:
                    include_admission = False
                    continue
                if limit == 50:
                    limit = 12
                    continue
                return FetchResult(output, complete=False, error=f"skip={skip}: {exc}")
            wrapper = data.get("docs") or {}
            docs = wrapper.get("docs") or []
            total = int(wrapper.get("count") or len(docs))
            for doc in docs:
                normalized = self.normalize(doc)
                if normalized: output.append(normalized)
            pages += 1
            skip += len(docs)
            if not docs or skip >= total:
                return FetchResult(output)
        return FetchResult(output, complete=False, error=f"reached {self.max_pages}-page safety limit")
