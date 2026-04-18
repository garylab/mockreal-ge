from __future__ import annotations

import re

import httpx
from loguru import logger as log
from tenacity import retry, stop_after_attempt, wait_exponential

from src.config import settings
from src.storage.models import ContentPackage
from src.storage.r2_client import upload_image


@retry(stop=stop_after_attempt(2), wait=wait_exponential(min=1, max=5))
async def _search_pexels(query: str) -> dict | None:
    async with httpx.AsyncClient(timeout=15) as client:
        resp = await client.get(
            "https://api.pexels.com/v1/search",
            params={"query": query, "per_page": 1, "orientation": "landscape"},
            headers={"Authorization": settings.pexels_api_key},
        )
        resp.raise_for_status()
        data = resp.json()
    photos = data.get("photos", [])
    return photos[0] if photos else None


async def _download(url: str) -> bytes:
    async with httpx.AsyncClient(timeout=30) as client:
        resp = await client.get(url)
        resp.raise_for_status()
        return resp.content


async def enrich(pkg: ContentPackage) -> ContentPackage:
    """Search Pexels per outline section, upload to R2, insert into article HTML."""
    if not settings.pexels_api_key or not settings.r2_endpoint:
        log.info("Skipping image enrichment (no Pexels/R2 credentials)")
        return pkg

    html = pkg.article_html
    images: list[dict] = []

    for section in pkg.outline[:6]:
        try:
            clean_section = re.sub(r"<[^>]*>", "", section)[:80]
            photo = await _search_pexels(f"{clean_section} career professional")
            if not photo:
                continue

            img_url = photo.get("src", {}).get("large2x") or photo.get("src", {}).get("large", "")
            if not img_url:
                continue

            img_bytes = await _download(img_url)
            filename = f"pexels-{photo['id']}.jpg"
            public_url = upload_image(img_bytes, filename)

            alt = (photo.get("alt") or clean_section).replace('"', "&quot;")
            credit = photo.get("photographer", "Pexels")
            ulink = photo.get("photographer_url") or photo.get("url", "https://www.pexels.com")

            images.append({"section": section, "url": public_url, "alt": alt, "credit": credit, "ulink": ulink})
        except Exception as exc:
            log.debug("Image enrichment failed for '{}': {}", section[:40], exc)

    h2_positions = [m.end() for m in re.finditer(r"</h2>", html, re.IGNORECASE)]
    for i in range(min(len(h2_positions), len(images)) - 1, -1, -1):
        img = images[i]
        tag = (
            f'<figure><img src="{img["url"]}" alt="{img["alt"]}" loading="lazy" width="800" />'
            f'<figcaption>Photo by <a href="{img["ulink"]}">'
            f'{img["credit"]}</a> on Pexels</figcaption></figure>'
        )
        pos = h2_positions[i]
        html = html[:pos] + "\n" + tag + html[pos:]

    pkg.article_html = html
    pkg.section_images = images
    log.info("Enriched '{}' with {} section images", pkg.article_title, len(images))
    return pkg
