from __future__ import annotations


from src.storage.models import RawSignal
from src.utils import serpapi_client
from loguru import logger as log



async def fetch_search() -> list[RawSignal]:
    results: list[RawSignal] = []
    data = await serpapi_client.google_search("AI mock interview preparation tips 2026")
    for item in data.get("organic_results", [])[:10]:
        results.append(RawSignal(
            title=item.get("title", ""),
            source="google_search",
            url=item.get("link", ""),
            snippet=item.get("snippet", "")[:300],
            engagement=11 - item.get("position", 10),
        ))
    log.info("Search: fetched %d results", len(results))
    return results
