import datetime
import html
import json
import re
import requests

from adapters.base import BaseAdapter
from adapters.utils import FetchResult, REGIONAL_TZ, json_text, strip_html, wall_clock_epoch_to_utc
import events as _events


class MercerCounty(BaseAdapter):
    source_key = "mercer_county"
    display_name = "Mercer County"
    homepage_url = "https://www.visitmercercountypa.com/"
    calendar_url = "https://www.visitmercercountypa.com/event-calendar/"
    ajax_url = "https://www.visitmercercountypa.com/?evo-ajax=eventon_init_load"

    def _bootstrap(self, coverage_days):
        session = requests.Session()
        page = session.get(self.calendar_url, timeout=30, headers={"User-Agent":"EventMapApp/1.0"})
        page.raise_for_status()
        text = page.text
        nonce_match = re.search(r'evo_general_params\s*=\s*\{.*?"n":"([^"]+)', text)
        sc_match = re.search(r"class='evo_cal_data' data-sc=\"([^\"]+)\"", text)
        cal_match = re.search(r"id='(evcal_calendar_\d+)'[^>]*ajax_loading_cal", text)
        if not nonce_match or not sc_match or not cal_match:
            raise ValueError("EventON bootstrap configuration not found")
        sc = json.loads(html.unescape(sc_match.group(1)))
        now = datetime.datetime.now(REGIONAL_TZ)
        sc.update({
            "fixed_day": str(now.day), "fixed_month": str(now.month), "fixed_year": str(now.year),
            "number_of_months": str(max(1, min(7, (int(coverage_days) + 30) // 31))),
            "hide_past": "yes", "show_repeats": "yes",
        })
        return session, nonce_match.group(1), cal_match.group(1), sc

    def _eventon_json(self, coverage_days):
        session, nonce, cal_id, sc = self._bootstrap(coverage_days)
        form = {"nonce": nonce, "nn": nonce, "uid": ""}
        for key, value in sc.items():
            form[f"cals[{cal_id}][sc][{key}]"] = str(value)
        response = session.post(self.ajax_url, data=form, timeout=60,
            headers={"User-Agent":"EventMapApp/1.0", "Referer":self.calendar_url, "Accept":"application/json"})
        response.raise_for_status()
        data = response.json()
        if data.get("status") == "bad":
            raise ValueError(data.get("msg") or "EventON rejected request")
        calendar = (data.get("cals") or {}).get(cal_id) or {}
        return data, calendar.get("json") or []

    def _rest_details(self, ids):
        details = {}
        for pos in range(0, len(ids), 100):
            response = requests.get(
                "https://www.visitmercercountypa.com/wp-json/wp/v2/ajde_events",
                params={"per_page":100, "include":",".join(ids[pos:pos+100]), "_embed":"1"}, timeout=30,
                headers={"User-Agent":"EventMapApp/1.0", "Accept":"application/json"})
            response.raise_for_status()
            for row in response.json(): details[str(row.get("id"))] = row
        return details

    def normalize(self, ev, detail=None):
        detail = detail or {}
        event_id = str(ev.get("event_id") or ev.get("ID") or "")
        start_raw = ev.get("event_start_unix")
        end_raw = ev.get("event_end_unix")
        start = wall_clock_epoch_to_utc(start_raw, REGIONAL_TZ)
        end = wall_clock_epoch_to_utc(end_raw, REGIONAL_TZ)
        occurrence_id = f"{event_id}:{ev.get('ri', '')}:{start_raw}"
        pmv = ev.get("event_pmv") or {}
        virtual = str((pmv.get("_virtual") or ["no"])[0]).lower() == "yes"
        title = strip_html(ev.get("event_title") or (detail.get("title") or {}).get("rendered")) or ""
        image = None
        embedded = detail.get("_embedded") or {}
        media = embedded.get("wp:featuredmedia") or []
        if media: image = media[0].get("source_url")
        return None if virtual else {
            "source_key": self.source_key, "source_event_id": occurrence_id,
            "source_url": detail.get("link") or self.homepage_url,
            "official_url": detail.get("link") or self.homepage_url, "title": title,
            "description_short": strip_html((detail.get("content") or {}).get("rendered"), 300),
            "start_datetime": start, "end_datetime": end, "date_label": None,
            "venue_name": None, "address": None, "city":"Mercer", "state":"PA", "postal_code":None,
            "latitude":None, "longitude":None, "category":None, "image_url":image, "admission":None,
            "normalized_fingerprint": _events.make_fingerprint(self.source_key, occurrence_id, start, title, detail.get("link")),
            "series_key": _events.make_series_key(self.source_key, event_id or title),
            "raw_source_json": json_text({"eventon":ev, "wordpress":detail}),
        }

    def fetch(self, coverage_days=60):
        try:
            root, rows = self._eventon_json(coverage_days)
            ids = sorted({str(row.get("event_id") or row.get("ID")) for row in rows if row.get("event_id") or row.get("ID")})
            details = self._rest_details(ids) if ids else {}
        except Exception as exc:
            return FetchResult([], complete=False, error=exc)
        output = []
        for row in rows:
            normalized = self.normalize(row, details.get(str(row.get("event_id") or row.get("ID"))))
            if normalized: output.append(normalized)
        return FetchResult(output)
