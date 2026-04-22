from __future__ import annotations


import httpx
from tenacity import retry, stop_after_attempt, wait_exponential

from src.config import settings
from src.utils.rate_limiter import api_semaphore


BASE = "https://serpapi.com/search.json"


@retry(stop=stop_after_attempt(2), wait=wait_exponential(min=1, max=10))
async def search(engine: str, params: dict | None = None) -> dict:
    async with api_semaphore:
        p = {
            "api_key": settings.serpapi_key,
            "engine": engine,
            **(params or {}),
        }
        async with httpx.AsyncClient(timeout=30) as client:
            resp = await client.get(BASE, params=p)
            resp.raise_for_status()
            return resp.json()


async def google_trends(query: str) -> dict:
    return await search("google_trends", {"q": query, "date": "now 7-d"})


async def google_news(query: str) -> dict:
    return await search("google_news_light", {"q": query, "gl": "us", "hl": "en"})


async def google_search(query: str) -> dict:
    return await search("google", {"q": query, "gl": "us", "hl": "en", "num": 10})


async def google_autocomplete(query: str) -> dict:
    return await search("google_autocomplete", {"q": query, "gl": "us", "hl": "en"})


async def youtube_search(query: str) -> dict:
    return await search("youtube", {"search_query": query})


async def people_also_ask(query: str) -> dict:
    return await search("google_related_questions", {"q": query, "gl": "us", "hl": "en"})


async def google_forums(query: str) -> dict:
    return await search("google_forums", {"q": query, "gl": "us", "hl": "en"})


async def google_scholar(query: str) -> dict:
    return await search("google_scholar", {"q": query, "hl": "en"})
