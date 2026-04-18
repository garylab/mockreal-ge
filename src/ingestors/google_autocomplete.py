from __future__ import annotations

import asyncio

from src.storage.models import RawSignal
from src.utils import serpapi_client
from loguru import logger as log


SEEDS = ["how to prepare for AI interview", "mock interview", "job interview anxiety", "career change after layoff"]


async def fetch_autocomplete() -> list[RawSignal]:
    results: list[RawSignal] = []
    tasks = [serpapi_client.google_autocomplete(q) for q in SEEDS]
    batches = await asyncio.gather(*tasks, return_exceptions=True)
    for batch in batches:
        if isinstance(batch, Exception):
            log.warning("Autocomplete error: {}", batch)
            continue
        for i, sug in enumerate(batch.get("suggestions", [])[:8]):
            results.append(RawSignal(
                title=sug.get("value", ""),
                source="google_autocomplete",
                engagement=8 - i,
            ))
    log.info("Autocomplete: fetched {} suggestions", len(results))
    return results
