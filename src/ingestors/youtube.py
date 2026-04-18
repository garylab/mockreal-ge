from __future__ import annotations


from src.storage.models import RawSignal
from src.utils import serpapi_client
from loguru import logger as log



async def fetch_youtube() -> list[RawSignal]:
    results: list[RawSignal] = []
    data = await serpapi_client.youtube_search("AI interview preparation tips")
    for item in data.get("video_results", [])[:10]:
        views = item.get("views", 0)
        if isinstance(views, str):
            views = int("".join(c for c in views if c.isdigit()) or "0")
        results.append(RawSignal(
            title=item.get("title", ""),
            source="youtube",
            url=item.get("link", ""),
            engagement=min(views / 1000, 100),
            snippet=item.get("description", "")[:300],
            extra={"channel": item.get("channel", {}).get("name", "")},
        ))
    log.info("YouTube: fetched %d videos", len(results))
    return results
