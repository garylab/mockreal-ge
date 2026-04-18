from __future__ import annotations

import asyncio

from src.storage.models import RawSignal
from src.utils import serpapi_client
from loguru import logger as log


QUERIES = ["AI interview", "job market", "career change", "tech layoffs", "AI tools productivity"]


async def fetch_trends() -> list[RawSignal]:
    results: list[RawSignal] = []
    tasks = [serpapi_client.google_trends(q) for q in QUERIES]
    batches = await asyncio.gather(*tasks, return_exceptions=True)
    for q, batch in zip(QUERIES, batches):
        if isinstance(batch, Exception):
            log.warning("Trends error for '{}': {}", q, batch)
            continue
        for story in batch.get("interest_over_time", {}).get("timeline_data", [])[-5:]:
            for val in story.get("values", []):
                results.append(RawSignal(
                    title=f"{q}: {val.get('query', q)}",
                    source="google_trends",
                    url="",
                    engagement=int(val.get("extracted_value", 0)),
                    extra={"date": story.get("date", "")},
                ))
        for rising in batch.get("rising_queries", []):
            for item in rising.get("queries", [])[:5]:
                results.append(RawSignal(
                    title=item.get("query", ""),
                    source="google_trends",
                    engagement=int(item.get("extracted_value", 0)),
                ))
    log.info("Trends: fetched {} signals", len(results))
    return results
