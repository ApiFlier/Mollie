"""
Pittsburgh Glass Center adapter.

Source: https://www.pittsburghglasscenter.org/events/
API:    WordPress + The Events Calendar (Tribe) REST API
Events: Walk-in glass-making sessions, free lecture series, exhibitions,
        open studio hours, and community workshops.
Note:   The Tribe API for this source omits venue data entirely. This adapter
        provides the known physical address (5472 Penn Ave, Pittsburgh PA 15206)
        as a fallback so distance filters and map pins work correctly.
Attribution: Events link to pittsburghglasscenter.org event pages.
"""
from adapters.tribe_events import TribeEventsAdapter

_FALLBACK = {
    "venue_name": "Pittsburgh Glass Center",
    "address":    "5472 Penn Ave",
    "city":       "Pittsburgh",
    "state":      "PA",
    "postal_code": "15206",
    "latitude":   40.4628,
    "longitude":  -79.9270,
}


class PittsburghGlassCenter(TribeEventsAdapter):
    source_key   = "pittsburgh_glass_center"
    display_name = "Pittsburgh Glass Center"
    api_base     = "https://www.pittsburghglasscenter.org"

    def fetch(self, coverage_days=60) -> list:
        events = super().fetch(coverage_days=coverage_days)
        # Venue data is missing from this source's API; apply known fallback.
        for ev in events:
            for field, value in _FALLBACK.items():
                if not ev.get(field):
                    ev[field] = value
        return events
