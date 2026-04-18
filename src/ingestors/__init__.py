from src.ingestors.reddit import fetch_reddit
from src.ingestors.google_trends import fetch_trends
from src.ingestors.google_news import fetch_news
from src.ingestors.google_search import fetch_search
from src.ingestors.google_autocomplete import fetch_autocomplete
from src.ingestors.youtube import fetch_youtube
from src.ingestors.people_also_ask import fetch_paa
from src.ingestors.top_performers import fetch_top_performers

ALL_INGESTORS = [
    fetch_reddit,
    fetch_trends,
    fetch_news,
    fetch_search,
    fetch_autocomplete,
    fetch_youtube,
    fetch_paa,
]

__all__ = [
    "ALL_INGESTORS",
    "fetch_reddit", "fetch_trends", "fetch_news", "fetch_search",
    "fetch_autocomplete", "fetch_youtube", "fetch_paa", "fetch_top_performers",
]
