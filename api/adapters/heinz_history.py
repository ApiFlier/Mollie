"""
Heinz History Center adapter.

Source: https://www.heinzhistorycenter.org/events/
API:    WordPress + The Events Calendar (Tribe) REST API
Attribution: Events link to heinzhistorycenter.org event pages.
"""
from adapters.tribe_events import TribeEventsAdapter


class HeinzHistory(TribeEventsAdapter):
    source_key   = "heinz_history"
    display_name = "Heinz History Center"
    api_base     = "https://www.heinzhistorycenter.org"
