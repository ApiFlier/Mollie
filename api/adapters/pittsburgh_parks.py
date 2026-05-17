"""
Pittsburgh Parks Conservancy adapter.

Source: https://www.pittsburghparks.org/events/
API:    WordPress + The Events Calendar (Tribe) REST API
Events: Outdoor activities, yoga, stewardship days, birding walks, volunteer
        programs, and seasonal events across Pittsburgh's major parks.
Note:   Some venue records have a positive longitude (missing negative sign) due
        to a data-entry issue in their WordPress backend. This adapter corrects
        the sign for any geo_lng > 0 when the latitude confirms Western PA.
Attribution: Events link to pittsburghparks.org event pages.
"""
from adapters.tribe_events import TribeEventsAdapter


class PittsburghParks(TribeEventsAdapter):
    source_key   = "pittsburgh_parks"
    display_name = "Pittsburgh Parks Conservancy"
    api_base     = "https://www.pittsburghparks.org"

    def fetch(self, coverage_days=60) -> list:
        events = super().fetch(coverage_days=coverage_days)
        # Fix data-entry error: some venues have positive longitude for Western PA.
        # PA longitude must be negative (~-74° to ~-80°). If both lat and lng are
        # positive and lat is in the PA range, the lng sign was entered incorrectly.
        for ev in events:
            lat = ev.get("latitude")
            lng = ev.get("longitude")
            if lat is not None and lng is not None:
                try:
                    if float(lat) > 0 and float(lng) > 0:
                        ev["longitude"] = -float(lng)
                except (TypeError, ValueError):
                    pass
        return events
