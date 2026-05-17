"""
Carnegie Museums of Pittsburgh adapter.

Source: https://carnegiemuseums.org/events/
API:    WordPress + The Events Calendar (Tribe) REST API
Venues: Carnegie Museum of Natural History, Carnegie Museum of Art,
        The Andy Warhol Museum, Carnegie Science Center, Powdermill Nature Reserve.
Attribution: Events link to carnegiemuseums.org and sub-museum event pages.
"""
from adapters.tribe_events import TribeEventsAdapter


class CarnegieMuseums(TribeEventsAdapter):
    source_key   = "carnegie_museums"
    display_name = "Carnegie Museums of Pittsburgh"
    api_base     = "https://carnegiemuseums.org"
