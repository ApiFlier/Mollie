from adapters.tribe_events import TribeEventsAdapter


class PlayPittsburgh(TribeEventsAdapter):
    source_key = "play_pittsburgh"
    display_name = "Play Pittsburgh"
    api_base = "https://playpittsburgh.com"
    homepage_url = "https://playpittsburgh.com/events/"
