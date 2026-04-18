from __future__ import annotations

import json
import re
import uuid

from src.content.prompts import CONTENT_SYSTEM, build_content_prompt
from src.storage.models import ContentPackage, ScoredTopic
from src.utils.ai_client import chat_claude
from loguru import logger as log

_H1_RE = re.compile(r"<h1[^>]*>.*?</h1>\s*", re.IGNORECASE | re.DOTALL)
_MD_TITLE_RE = re.compile(r"^#\s+.+\n+", re.MULTILINE)


def _strip_title_from_html(html: str) -> str:
    return _H1_RE.sub("", html, count=1).lstrip()


def _strip_title_from_md(md: str) -> str:
    return _MD_TITLE_RE.sub("", md, count=1).lstrip()


async def generate(topic: ScoredTopic) -> ContentPackage:
    """Generate a full content package from a scored topic using Claude."""
    user_msg = build_content_prompt(topic.model_dump())

    raw = await chat_claude(
        user_message=user_msg,
        system=CONTENT_SYSTEM,
        max_tokens=8192,
        temperature=0.6,
    )

    cleaned = raw.strip()
    if cleaned.startswith("```"):
        cleaned = cleaned.split("\n", 1)[-1].rsplit("```", 1)[0]

    try:
        data = json.loads(cleaned)
    except json.JSONDecodeError:
        log.error("Failed to parse content JSON for topic: {}", topic.title)
        data = {"article_title": topic.title, "article_html": cleaned}

    article_html = _strip_title_from_html(data.get("article_html", ""))
    medium_article = _strip_title_from_md(data.get("medium_article", ""))

    pkg = ContentPackage(
        content_id=uuid.uuid4().hex[:16],
        topic=topic,
        article_title=data.get("article_title", topic.title),
        outline=data.get("outline", []),
        article_html=article_html,
        medium_article=medium_article,
        social_posts=data.get("social_posts", {}),
        social_posts_variant_b=data.get("social_posts_variant_b", {}),
        seo_keywords=data.get("seo_keywords", []),
        meta_description=data.get("meta_description", ""),
        cta_variant_a=data.get("cta_variant_a", ""),
        cta_variant_b=data.get("cta_variant_b", ""),
    )
    log.info("Generated content: '{}' ({} chars HTML)", pkg.article_title, len(pkg.article_html))
    return pkg
