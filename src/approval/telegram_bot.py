from __future__ import annotations

import json

import httpx

from src.config import settings
from src.storage.models import ContentPackage
from loguru import logger as log


_BASE = "https://api.telegram.org/bot{token}"


async def send_for_approval(pkg: ContentPackage) -> None:
    """Send a Telegram message with inline Approve/Reject buttons."""
    if not settings.telegram_bot_token or not settings.telegram_chat_id:
        log.warning("Telegram not configured, skipping approval for '{}'", pkg.article_title)
        return

    preview = pkg.article_html[:400].replace("<", "&lt;").replace(">", "&gt;")
    text = (
        f"<b>New Article for Review</b>\n\n"
        f"<b>Title:</b> {pkg.article_title}\n"
        f"<b>Score:</b> {pkg.topic.score if pkg.topic else 'N/A'}\n"
        f"<b>Cluster:</b> {pkg.topic.cluster if pkg.topic else 'N/A'}\n"
        f"<b>Priority:</b> {pkg.topic.priority.value if pkg.topic else 'N/A'}\n\n"
        f"<b>Preview:</b>\n{preview}...\n\n"
        f"<b>CTA-A:</b> {pkg.cta_variant_a[:100]}\n"
        f"<b>CTA-B:</b> {pkg.cta_variant_b[:100]}\n\n"
        f"ID: <code>{pkg.content_id}</code>"
    )

    keyboard = {
        "inline_keyboard": [[
            {"text": "✅ Approve", "callback_data": json.dumps({"action": "approve", "id": pkg.content_id})},
            {"text": "❌ Reject", "callback_data": json.dumps({"action": "reject", "id": pkg.content_id})},
        ]]
    }

    url = _BASE.format(token=settings.telegram_bot_token) + "/sendMessage"
    payload = {
        "chat_id": settings.telegram_chat_id,
        "text": text,
        "parse_mode": "HTML",
        "reply_markup": json.dumps(keyboard),
    }

    async with httpx.AsyncClient(timeout=15) as client:
        resp = await client.post(url, json=payload)
        if resp.status_code != 200:
            log.error("Telegram send failed: {}", resp.text)
        else:
            log.info("Sent approval request for '{}' to Telegram", pkg.article_title)
