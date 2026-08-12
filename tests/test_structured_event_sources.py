import datetime
import os
import sys
import unittest
from unittest.mock import MagicMock, patch

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "api"))
for _module_name in list(sys.modules):
    if _module_name == "adapters" or _module_name.startswith("adapters.") or _module_name in ("events", "requests"):
        sys.modules.pop(_module_name, None)

from adapters.play_pittsburgh import PlayPittsburgh
from adapters.kidsburgh import Kidsburgh
from adapters.tribe_events import TribeEventsAdapter, _normalize as tribe_normalize
from adapters.experience_butler import ExperienceButler
from adapters.simpleview import SimpleviewEventsAdapter
from adapters.visit_pa import VisitPA
from adapters.laurel_highlands import LaurelHighlands
from adapters.pittsburgh_magazine import PittsburghMagazine
from adapters.mercer_county import MercerCounty
from adapters.utils import FetchResult, wall_clock_epoch_to_utc
import events


class TestTribeSources(unittest.TestCase):
    def test_play_is_shared_tribe(self):
        self.assertIsInstance(PlayPittsburgh(), TribeEventsAdapter)
        self.assertEqual(PlayPittsburgh.source_key, "play_pittsburgh")

    def test_kidsburgh_is_shared_tribe(self):
        self.assertIsInstance(Kidsburgh(), TribeEventsAdapter)
        self.assertEqual(Kidsburgh.source_key, "kidsburgh")

    def test_utc_fields_preferred(self):
        row = tribe_normalize({"id":1,"title":"X","utc_start_date":"2026-07-01 14:00:00","start_date":"2026-07-01 10:00:00","timezone":"America/New_York"}, "x")
        self.assertEqual(row["start_datetime"], "2026-07-01 14:00:00")

    def test_winter_est_conversion(self):
        row = tribe_normalize({"id":1,"title":"X","start_date":"2026-01-01 10:00:00"}, "x")
        self.assertEqual(row["start_datetime"], "2026-01-01 15:00:00")

    def test_multiple_venues_use_first_structured_venue(self):
        row = tribe_normalize({"id": 1, "title": "X", "venue": [{"venue": "Museum", "address": "1 Main"}]}, "x")
        self.assertEqual(row["venue_name"], "Museum")


class TestExperienceButler(unittest.TestCase):
    def fixture(self, oid="abc"):
        return {"objectID":oid,"id":44,"distinctField":"series-44","title":"Butler Event","uri":"butler-event","typeHandle":"event","sectionHandle":"events","content":"Hello","primaryImageUrl":"https://x/img.jpg","eventCategories":["Family"],"_geoloc":{"lat":40.8,"lng":-79.9},"address":["Venue","1 Main St","Butler, Pennsylvania 16001"],"startDate":1782914400,"endDate":1782921600}

    def test_normalization_coordinates_url_identity(self):
        row = ExperienceButler().normalize(self.fixture())
        self.assertEqual((row["latitude"], row["longitude"]), (40.8, -79.9))
        self.assertEqual(row["source_event_id"], "abc")
        self.assertEqual(row["source_url"], "https://www.experiencebutler.com/events/butler-event/")

    def test_occurrences_use_object_id(self):
        a = ExperienceButler().normalize(self.fixture("one"))
        b = ExperienceButler().normalize(self.fixture("two"))
        self.assertNotEqual(a["normalized_fingerprint"], b["normalized_fingerprint"])
        self.assertEqual(a["series_key"], b["series_key"])

    def test_pagination_stops_at_nbpages(self):
        adapter = ExperienceButler()
        adapter.queries = ("",)
        adapter._request = MagicMock(side_effect=[{"hits":[self.fixture("1")],"nbPages":2},{"hits":[self.fixture("2")],"nbPages":2}])
        result = adapter.fetch()
        self.assertEqual(len(result), 2)
        self.assertEqual(adapter._request.call_count, 2)


class TestSimpleview(unittest.TestCase):
    def fixture(self):
        return {"_id":"x","recid":123,"title":"Festival","date":"2026-11-01T04:59:59Z","url":"/event/festival/","location":"Square","city":"Ligonier","region":"PA","latitude":40.2,"longitude":-79.2,"categories":[{"catId":"62"}],"media_raw":[{"resource_url":"https://x/i.jpg"}]}

    def test_visit_pa_and_laurel_normalize(self):
        self.assertEqual(VisitPA().normalize(self.fixture())["source_key"], "visit_pa")
        self.assertEqual(LaurelHighlands().normalize(self.fixture())["category"], "Family Fun")

    def test_occurrence_uses_recid_and_date(self):
        row = LaurelHighlands().normalize(self.fixture())
        self.assertTrue(row["source_event_id"].startswith("123:"))
        self.assertTrue(row["start_datetime"].endswith("04:00:00"))

    def test_dst_safe_boundaries(self):
        adapter = VisitPA()
        summer = adapter._boundaries(1, datetime.datetime(2026,7,1,12,tzinfo=adapter._boundaries.__globals__["REGIONAL_TZ"]))[0]
        winter = adapter._boundaries(1, datetime.datetime(2026,1,1,12,tzinfo=adapter._boundaries.__globals__["REGIONAL_TZ"]))[0]
        self.assertIn("T04:00:00", summer)
        self.assertIn("T05:00:00", winter)

    def test_skip_pagination(self):
        adapter = VisitPA(); docs = [self.fixture()]
        adapter._get_page = MagicMock(side_effect=[{"docs":{"count":2,"docs":docs}}, {"docs":{"count":2,"docs":docs}}])
        self.assertEqual(len(adapter.fetch()), 2)
        self.assertEqual(adapter._get_page.call_args_list[1].args[1], 1)


class TestEvvnt(unittest.TestCase):
    def fixture(self):
        return {"source_id":77,"event_parent_id":9,"title":"Show","start_time":"2026-07-01T20:00:00-04:00","end_time":"2026-07-01T22:00:00-04:00","category_name":"Theatre","prices":{"Adult":"USD 80.0","Child":"USD 20.0"},"source_broadcast_url":"https://mag/event","original_links":{"Tickets":"https://tickets/direct"},"links":{"Tickets":"https://go.evvnt.com/x"},"venue":{"name":"Hall","latitude":40.4,"longitude":-80.0,"town":"Pittsburgh","region":"PA"}}

    def test_identity_series_timezone_links_prices_venue(self):
        row = PittsburghMagazine().normalize(self.fixture())
        self.assertEqual(row["source_event_id"], "77")
        self.assertEqual(row["start_datetime"], "2026-07-02 00:00:00")
        self.assertEqual(row["official_url"], "https://tickets/direct")
        self.assertEqual(row["admission"], "$20–$80")
        self.assertEqual(row["venue_name"], "Hall")
        other = self.fixture(); other["source_id"] = 78
        self.assertEqual(row["series_key"], PittsburghMagazine().normalize(other)["series_key"])

    def test_pagination(self):
        response = MagicMock(); response.raise_for_status.return_value=None; response.json.return_value={"rawEvents":[]}
        with patch("adapters.evvnt.requests.get", return_value=response) as get:
            self.assertEqual(PittsburghMagazine().fetch(), [])
        self.assertEqual(get.call_count, 1)


class TestEventOn(unittest.TestCase):
    def test_wall_clock_epoch_ignores_bad_event_timezone(self):
        epoch = datetime.datetime(2026,8,1,9,0,tzinfo=datetime.timezone.utc).timestamp()
        row = MercerCounty().normalize({"event_id":5,"ID":5,"ri":"0","event_start_unix":epoch,"event_end_unix":epoch+3600,"event_title":"Market","event_pmv":{"_evo_tz":["Pacific/Midway"]}})
        self.assertEqual(row["start_datetime"], "2026-08-01 13:00:00")
        self.assertIn(":0:", row["source_event_id"])

    def test_recurring_occurrence_identity(self):
        adapter=MercerCounty(); base={"event_id":5,"event_title":"X","event_end_unix":2}
        a=adapter.normalize(dict(base,ri="0",event_start_unix=1)); b=adapter.normalize(dict(base,ri="1",event_start_unix=2))
        self.assertNotEqual(a["normalized_fingerprint"],b["normalized_fingerprint"])
        self.assertEqual(a["series_key"],b["series_key"])


class TestRefreshSafety(unittest.TestCase):
    def test_validation_coerces_long_admission(self):
        row = events._validate_event({"source_key": "x", "title": "X", "normalized_fingerprint": "fp", "admission": "a" * 300})
        self.assertEqual(len(row["admission"]), 255)

    def test_incomplete_fetch_marks_error_without_cleanup(self):
        adapter=MagicMock(source_key="partial",display_name="Partial",homepage_url=None)
        adapter.fetch.return_value=FetchResult([{"title":"x"}],complete=False,error="page 2 failed")
        old=events._ADAPTERS; events._ADAPTERS={"partial":adapter}
        try:
            conn=MagicMock()
            with patch.object(events,"_ensure_source"), patch.object(events,"get_source_coverage_days",return_value=60), patch.object(events,"_mark_error") as mark, patch.object(events,"_purge_stale_for_source") as purge:
                self.assertEqual(events.refresh_source(conn,"partial"),0)
                mark.assert_called_once(); purge.assert_not_called()
        finally: events._ADAPTERS=old


if __name__ == "__main__": unittest.main()
