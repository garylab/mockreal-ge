from __future__ import annotations


from src.storage.models import RawSignal
from src.utils import serpapi_client
from loguru import logger as log



async def fetch_news() -> list[RawSignal]:
    results: list[RawSignal] = []
    data = await serpapi_client.google_news("AI interview OR job market OR tech layoffs OR hiring trends")
    for item in data.get("news_results", [])[:20]:
        results.append(RawSignal(
            title=item.get("title", ""),
            source="google_news",
            url=item.get("link", ""),
            snippet=item.get("snippet", "")[:300],
            engagement=10,
            extra={"source_name": item.get("source", {}).get("name", "")},
        ))
    log.info("News: fetched %d articles", len(results))
    return results
