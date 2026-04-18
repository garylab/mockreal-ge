from __future__ import annotations


import httpx
from tenacity import retry, stop_after_attempt, wait_exponential

from src.config import settings
from src.publishers.base import BasePublisher, PublishResult
from src.storage.models import ContentPackage
from loguru import logger as log



class LinkedInPublisher(BasePublisher):
    platform = "linkedin"

    @retry(stop=stop_after_attempt(2), wait=wait_exponential(min=2, max=10))
    async def publish(self, pkg: ContentPackage, cta_variant: str = "a") -> PublishResult:
        if not settings.linkedin_access_token or not settings.linkedin_person_urn:
            return PublishResult(self.platform, "", False, "LinkedIn not configured")

        social = self._pick_social(pkg, cta_variant)
        text = social.get("linkedin", pkg.article_title)

        payload = {
            "author": f"urn:li:person:{settings.linkedin_person_urn}",
            "lifecycleState": "PUBLISHED",
            "specificContent": {
                "com.linkedin.ugc.ShareContent": {
                    "shareCommentary": {"text": text},
                    "shareMediaCategory": "ARTICLE",
                    "media": [{
                        "status": "READY",
                        "originalUrl": pkg.featured_image_url or settings.website_api_url,
                        "title": {"text": pkg.article_title},
                    }],
                }
            },
            "visibility": {"com.linkedin.ugc.MemberNetworkVisibility": "PUBLIC"},
        }

        async with httpx.AsyncClient(timeout=30) as client:
            resp = await client.post(
                "https://api.linkedin.com/v2/ugcPosts",
                json=payload,
                headers={"Authorization": f"Bearer {settings.linkedin_access_token}"},
            )
            resp.raise_for_status()
            data = resp.json()

        post_id = data.get("id", "")
        log.info("Published to LinkedIn: {}", post_id)
        return PublishResult(self.platform, post_id, True, post_body=text)
