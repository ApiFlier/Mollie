from adapters.tribe_events import TribeEventsAdapter


class Kidsburgh(TribeEventsAdapter):
    source_key = "kidsburgh"
    display_name = "Kidsburgh"
    api_base = "https://www.kidsburgh.org"
    homepage_url = "https://www.kidsburgh.org/events/"
