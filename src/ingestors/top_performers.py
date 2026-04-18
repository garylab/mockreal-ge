from __future__ import annotations


from src.storage import database as db
from loguru import logger as log



async def fetch_top_performers() -> list[dict]:
    rows = await db.fetch_top_performers(limit=10)
    results = [dict(r) for r in rows]
    log.info("Top performers: fetched %d records", len(results))
    return results
