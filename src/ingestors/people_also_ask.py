from __future__ import annotations


from src.storage.models import RawSignal
from src.utils import serpapi_client
from loguru import logger as log



async def fetch_paa() -> list[RawSignal]:
    results: list[RawSignal] = []
    data = await serpapi_client.people_also_ask("AI mock interview preparation tips")
    for i, item in enumerate(data.get("related_questions", [])[:8]):
        results.append(RawSignal(
            title=item.get("question", ""),
            source="people_also_ask",
            url=item.get("link", ""),
            snippet=item.get("snippet", "")[:300],
            engagement=8 - i,
        ))
    log.info("PAA: fetched {} questions", len(results))
    return results
