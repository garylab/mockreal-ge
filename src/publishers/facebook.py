from __future__ import annotations


import httpx
from tenacity import retry, stop_after_attempt, wait_exponential

from src.config import settings
from src.publishers.base import BasePublisher, PublishResult
from src.storage.models import ContentPackage
from loguru import logger as log



class FacebookPublisher(BasePublisher):
    platform = "facebook"

    @retry(stop=stop_after_attempt(2), wait=wait_exponential(min=2, max=10))
    async def publish(self, pkg: ContentPackage, cta_variant: str = "a") -> PublishResult:
        if not settings.facebook_page_id or not settings.facebook_access_token:
            return PublishResult(self.platform, "", False, "Facebook not configured")

        social = self._pick_social(pkg, cta_variant)
        message = social.get("facebook", pkg.article_title)

        payload = {
            "message": message,
            "link": pkg.featured_image_url or settings.website_api_url,
            "access_token": settings.facebook_access_token,
        }

        url = f"https://graph.facebook.com/v19.0/{settings.facebook_page_id}/feed"
        async with httpx.AsyncClient(timeout=30) as client:
            resp = await client.post(url, json=payload)
            resp.raise_for_status()
            data = resp.json()

        post_id = data.get("id", "")
        log.info("Published to Facebook: %s", post_id)
        return PublishResult(self.platform, post_id, True)
