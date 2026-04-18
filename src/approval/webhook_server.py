from __future__ import annotations

import json

from fastapi import APIRouter, Request

from src.storage import database as db
from loguru import logger as log


router = APIRouter()

_publish_callback = None


def set_publish_callback(fn):
    """Register the function to call when content is approved."""
    global _publish_callback
    _publish_callback = fn


@router.post("/webhook/telegram")
async def telegram_callback(request: Request):
    """Handle Telegram inline button callbacks."""
    body = await request.json()
    callback = body.get("callback_query")
    if not callback:
        return {"ok": True}

    data_str = callback.get("data", "{}")
    try:
        data = json.loads(data_str)
    except json.JSONDecodeError:
        return {"ok": True}

    action = data.get("action")
    content_id = data.get("id")
    if not action or not content_id:
        return {"ok": True}

    if action == "approve":
        await db.update_content_status(content_id, "approved")
        log.info("Content %s APPROVED", content_id)
        if _publish_callback:
            row = await db.get_pending_approval(content_id)
            if row:
                await _publish_callback(content_id)
    elif action == "reject":
        await db.update_content_status(content_id, "rejected")
        log.info("Content %s REJECTED", content_id)

    return {"ok": True}


@router.post("/webhook/tracking")
async def tracking_event(request: Request):
    """Receive tracking events (CTR, clicks, signups) from external systems."""
    body = await request.json()
    content_id = body.get("content_id")
    platform = body.get("platform")
    if not content_id or not platform:
        return {"error": "missing content_id or platform"}

    await db.upsert_performance(
        content_id=content_id,
        platform=platform,
        impressions=body.get("impressions", 0),
        clicks=body.get("clicks", 0),
        signups=body.get("signups", 0),
        ctr=body.get("ctr", 0),
        conversion_rate=body.get("conversion_rate", 0),
    )
    log.info("Tracking event: %s / %s", content_id, platform)
    return {"ok": True}
