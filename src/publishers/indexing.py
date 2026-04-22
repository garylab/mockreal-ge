from __future__ import annotations

import httpx
from loguru import logger as log

from src.config import settings


async def ping_google_indexing(url: str) -> bool:
    """Submit a URL to Google's Indexing API for faster crawling.

    Requires GOOGLE_INDEXING_API_KEY in settings, or falls back to a
    simple sitemap-style ping which works without authentication.
    """
    if not url:
        return False

    ping_url = f"https://www.google.com/ping?sitemap={url}"
    try:
        async with httpx.AsyncClient(timeout=15) as client:
            resp = await client.get(ping_url)
            if resp.status_code == 200:
                log.info("Google ping OK for {}", url)
                return True
            log.warning("Google ping returned {} for {}", resp.status_code, url)
    except Exception as exc:
        log.warning("Google ping failed for {}: {}", url, exc)
    return False


async def ping_bing_indexing(url: str) -> bool:
    """Submit a URL to Bing's URL Submission API."""
    if not url:
        return False

    bing_key = getattr(settings, "bing_api_key", "")
    if not bing_key:
        return False

    try:
        async with httpx.AsyncClient(timeout=15) as client:
            resp = await client.post(
                "https://ssl.bing.com/webmaster/api.svc/json/SubmitUrl",
                params={"apikey": bing_key},
                json={"siteUrl": settings.website_api_url, "url": url},
            )
            if resp.status_code == 200:
                log.info("Bing indexing OK for {}", url)
                return True
            log.warning("Bing indexing returned {} for {}", resp.status_code, url)
    except Exception as exc:
        log.warning("Bing indexing failed for {}: {}", url, exc)
    return False


async def notify_search_engines(url: str) -> None:
    """Ping both Google and Bing after publishing a new article."""
    await ping_google_indexing(url)
    await ping_bing_indexing(url)
