from __future__ import annotations


import httpx

from src.storage.models import ContentPackage
from src.storage.r2_client import upload_image
from src.utils.ai_client import generate_image_dalle
from loguru import logger as log



async def generate_featured(pkg: ContentPackage) -> ContentPackage:
    """Generate a featured image via DALL-E and upload to R2."""
    prompt = (
        f"Modern professional blog header: {pkg.article_title}. "
        "Clean minimalist tech, career theme, gradient, no text."
    )

    try:
        dalle_url = await generate_image_dalle(prompt)
        if not dalle_url:
            return pkg

        async with httpx.AsyncClient(timeout=30) as client:
            resp = await client.get(dalle_url)
            resp.raise_for_status()
            img_bytes = resp.content

        filename = f"featured-{pkg.content_id}.png"
        public_url = upload_image(img_bytes, filename, content_type="image/png")
        pkg.featured_image_url = public_url
        log.info("Featured image for '{}': {}", pkg.article_title, public_url)
    except Exception as exc:
        log.warning("Featured image generation failed: {}", exc)

    return pkg
