"""
Carnegie Library of Pittsburgh (CLP) adapter.

Source: https://www.carnegielibrary.org/events/
API:    WordPress + The Events Calendar (Tribe) REST API
Venues: 19 CLP branch locations across Pittsburgh neighborhoods.
        Events are almost entirely free community programming —
        storytimes, book clubs, art workshops, author talks, etc.
Attribution: Events link to carnegielibrary.org event pages.
"""
from adapters.tribe_events import TribeEventsAdapter


class CarnegieLibrary(TribeEventsAdapter):
    source_key   = "carnegie_library"
    display_name = "Carnegie Library of Pittsburgh"
    api_base     = "https://www.carnegielibrary.org"
