import os
from adapters.simpleview import SimpleviewEventsAdapter


class LaurelHighlands(SimpleviewEventsAdapter):
    source_key = "laurel_highlands"
    display_name = "Laurel Highlands"
    homepage_url = "https://www.golaurelhighlands.com/events/"
    base_url = "https://www.golaurelhighlands.com"
    token = os.environ.get("LAUREL_SIMPLEVIEW_TOKEN", "3e0c7cc3125bd4c48ede37f22b2f2f9c")
    category_ids = ("87","60","82","61","83","84","70","79","73","62","71","63","64","77","80","81","65","66","67","68","85","72","69","86","74")
    category_map = {"61":"Art Exhibits & Museums","62":"Family Fun","64":"Food and Drink","65":"Heritage","67":"Music & Dance","68":"Outdoor","72":"Summer Concerts / Live Music","79":"Dining Specials","81":"Health & Wellness","82":"Art Classes","87":"America250PA"}
