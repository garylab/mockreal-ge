from __future__ import annotations


import httpx

from src.config import settings
from src.storage import database as db
from loguru import logger as log



async def export_dashboard() -> None:
    """Export aggregated metrics to external dashboard webhook."""
    if not settings.dashboard_webhook_url:
        log.debug("No dashboard webhook configured, skipping export")
        return

    feedback = await db.fetch_cluster_feedback()
    payload = {
        "type": "dashboard_snapshot",
        "clusters": [
            {
                "cluster": str(r["cluster"]),
                "total_posts": int(r["total_posts"]),
                "avg_ctr": float(r["avg_ctr"]),
                "avg_conversion": float(r["avg_conversion"]),
            }
            for r in feedback
        ],
    }

    try:
        async with httpx.AsyncClient(timeout=15) as client:
            resp = await client.post(settings.dashboard_webhook_url, json=payload)
            resp.raise_for_status()
        log.info("Exported dashboard data ({} clusters)", len(payload["clusters"]))
    except Exception as exc:
        log.warning("Dashboard export failed: {}", exc)
