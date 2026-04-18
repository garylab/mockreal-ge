from __future__ import annotations

import httpx
from loguru import logger as log

from src.config import settings
from src.storage.models import ContentPackage
from src.storage.r2_client import upload_image
from src.utils.screenshot import capture_url, screenshot_and_upload


async def _search_pexels_featured(query: str) -> bytes | None:
    """Search Pexels for a high-quality landscape image and return its bytes."""
    if not settings.pexels_api_key:
        return None
    try:
        async with httpx.AsyncClient(timeout=15) as client:
            resp = await client.get(
                "https://api.pexels.com/v1/search",
                params={"query": query, "per_page": 5, "orientation": "landscape"},
                headers={"Authorization": settings.pexels_api_key},
            )
            resp.raise_for_status()
            photos = resp.json().get("photos", [])

        if not photos:
            return None

        best = max(photos, key=lambda p: p.get("width", 0) * p.get("height", 0))
        img_url = best.get("src", {}).get("original") or best.get("src", {}).get("large2x", "")
        if not img_url:
            return None

        async with httpx.AsyncClient(timeout=30) as client:
            resp = await client.get(img_url)
            resp.raise_for_status()
            return resp.content
    except Exception as exc:
        log.debug("Pexels featured search failed: {}", exc)
        return None


def _extract_website_url(pkg: ContentPackage) -> str | None:
    """Check if the article references a specific website/tool worth screenshotting."""
    source_urls = pkg.topic.source_urls if pkg.topic else []
    for url in source_urls:
        if any(d in url for d in ("reddit.com", "google.com/trends", "serpapi.com")):
            continue
        if url.startswith("http"):
            return url
    return None


async def generate_featured(pkg: ContentPackage) -> ContentPackage:
    """Generate a featured/main image: screenshot if title relates to a site, otherwise Pexels."""
    try:
        website_url = _extract_website_url(pkg)
        if website_url:
            public_url = await screenshot_and_upload(
                capture_url, website_url, filename_prefix="featured",
            )
            if public_url:
                pkg.featured_image_url = public_url
                log.info("Featured image (screenshot) for '{}': {}", pkg.article_title, public_url)
                return pkg

        query = f"{pkg.article_title} career professional technology"
        img_bytes = await _search_pexels_featured(query)
        if img_bytes:
            filename = f"featured-{pkg.content_id}.jpg"
            public_url = upload_image(img_bytes, filename, content_type="image/jpeg")
            pkg.featured_image_url = public_url
            log.info("Featured image (pexels) for '{}': {}", pkg.article_title, public_url)
            return pkg

        log.warning("No featured image found for '{}'", pkg.article_title)
    except Exception as exc:
        log.warning("Featured image generation failed: {}", exc)

    return pkg
