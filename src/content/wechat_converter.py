from __future__ import annotations

from src.content.prompts import WECHAT_SYSTEM
from src.storage.models import ContentPackage
from src.utils.ai_client import chat_claude
from loguru import logger as log


async def convert_to_wechat(pkg: ContentPackage) -> ContentPackage:
    """Convert the existing article_html into a WeChat Official Account article."""
    if not pkg.article_html:
        return pkg

    user_msg = (
        f"Title: {pkg.article_title}\n\n"
        f"Original article HTML:\n{pkg.article_html}"
    )

    raw = await chat_claude(
        user_message=user_msg,
        system=WECHAT_SYSTEM,
        max_tokens=6000,
        temperature=0.4,
    )

    cleaned = raw.strip()
    if cleaned.startswith("```"):
        cleaned = cleaned.split("\n", 1)[-1].rsplit("```", 1)[0].strip()

    if cleaned and "<" in cleaned:
        pkg.wechat_article = cleaned
        log.info("WeChat article generated: '{}' ({} chars)", pkg.article_title, len(cleaned))
    else:
        log.warning("WeChat conversion returned unexpected format for '{}'", pkg.article_title)

    return pkg
