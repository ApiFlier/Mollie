"""
WQED Cultural Calendar adapter.

Source: https://www.wqed.org/cultural-calendar/
API:    WordPress + The Events Calendar (Tribe) REST API
        Community-submitted cultural events across the Pittsburgh region:
        concerts, film screenings, lectures, exhibitions, festivals.
        Geo coordinates are not provided by this source; events will
        not appear in distance-filtered views but are searchable.
Attribution: Events link to wqed.org and each event's own page.
"""
from adapters.tribe_events import TribeEventsAdapter


class WqedCultural(TribeEventsAdapter):
    source_key   = "wqed_cultural"
    display_name = "WQED Cultural Calendar"
    api_base     = "https://www.wqed.org"
