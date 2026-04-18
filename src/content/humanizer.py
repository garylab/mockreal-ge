from __future__ import annotations

import json

from src.content.prompts import HUMANIZE_SYSTEM
from src.storage.models import ContentPackage
from src.utils.ai_client import chat_claude
from loguru import logger as log



async def humanize(pkg: ContentPackage) -> ContentPackage:
    """Rewrite content to remove AI patterns and add human texture."""
    payload = json.dumps({
        "article_html": pkg.article_html,
        "medium_article": pkg.medium_article,
        "social_posts": pkg.social_posts,
        "social_posts_variant_b": pkg.social_posts_variant_b,
    })

    raw = await chat_claude(
        user_message=f"Humanize this content package. Return ONLY valid JSON, no markdown fences:\n\n{payload}",
        system=HUMANIZE_SYSTEM,
        max_tokens=10000,
        temperature=0.7,
    )

    cleaned = raw.strip()
    if cleaned.startswith("```"):
        cleaned = cleaned.split("\n", 1)[-1].rsplit("```", 1)[0]

    try:
        data = json.loads(cleaned)
    except json.JSONDecodeError:
        log.warning("Humanize parse failed for '%s', keeping original", pkg.article_title)
        return pkg

    if data.get("article_html"):
        pkg.article_html = data["article_html"]
    if data.get("medium_article"):
        pkg.medium_article = data["medium_article"]
    if data.get("social_posts"):
        pkg.social_posts = data["social_posts"]
    if data.get("social_posts_variant_b"):
        pkg.social_posts_variant_b = data["social_posts_variant_b"]
    pkg.humanized = True

    log.info("Humanized content: '%s'", pkg.article_title)
    return pkg
