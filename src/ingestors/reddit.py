from __future__ import annotations


import httpx
from tenacity import retry, stop_after_attempt, wait_exponential

from src.storage.models import RawSignal
from loguru import logger as log


SUBREDDITS = ["entrepreneur", "startups", "artificial", "careerguidance", "cscareerquestions"]


@retry(stop=stop_after_attempt(2), wait=wait_exponential(min=1, max=10))
async def _fetch_subreddit(sub: str) -> list[dict]:
    url = f"https://www.reddit.com/r/{sub}/hot.json?limit=15"
    async with httpx.AsyncClient(timeout=15) as client:
        resp = await client.get(url, headers={"User-Agent": "mockreal-bot/1.0"})
        resp.raise_for_status()
        data = resp.json()
    posts = data.get("data", {}).get("children", [])
    return [p["data"] for p in posts if p.get("data")]


async def fetch_reddit() -> list[RawSignal]:
    import asyncio
    results: list[RawSignal] = []
    tasks = [_fetch_subreddit(sub) for sub in SUBREDDITS]
    batches = await asyncio.gather(*tasks, return_exceptions=True)
    for batch in batches:
        if isinstance(batch, Exception):
            log.warning("Reddit fetch error: %s", batch)
            continue
        for post in batch:
            results.append(RawSignal(
                title=post.get("title", ""),
                source="reddit",
                url=f"https://reddit.com{post.get('permalink', '')}",
                engagement=post.get("ups", 0),
                snippet=post.get("selftext", "")[:300],
                extra={"subreddit": post.get("subreddit", ""), "num_comments": post.get("num_comments", 0)},
            ))
    log.info("Reddit: fetched %d posts", len(results))
    return results
