import os
from adapters.simpleview import SimpleviewEventsAdapter


class VisitPA(SimpleviewEventsAdapter):
    source_key = "visit_pa"
    display_name = "VisitPA"
    homepage_url = "https://www.visitpa.com/events"
    base_url = "https://www.visitpa.com"
    token = os.environ.get("VISIT_PA_SIMPLEVIEW_TOKEN", "e23d5076b685912b323caecf66629183")
    category_ids = ("44","33","8","77","28","32","17","18","19","43","21","24","61","26","58","12","11","40","10","114","37","46","6")
    category_map = {"17":"Fairs & Festivals","19":"Family Fun","26":"History & Heritage","11":"Outdoor Adventure","12":"Live Music","40":"Performing Arts","44":"America250","6":"Tours & Sightseeing"}
