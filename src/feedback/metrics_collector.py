from __future__ import annotations


from src.storage import database as db
from loguru import logger as log



async def collect_and_compute(days: int = 7) -> list[dict]:
    """Fetch recent publishes and compute aggregated metrics per content+platform."""
    rows = await db.fetch_recent_publishes(days)
    by_key: dict[str, dict] = {}

    for r in rows:
        key = f"{r['content_id']}_{r['platform']}"
        if key not in by_key:
            by_key[key] = {
                "content_id": r["content_id"],
                "platform": r["platform"],
                "cluster": r["cluster"],
                "title": r["title"],
                "cta_variant": r["cta_variant"],
                "clicks": 0,
                "signups": 0,
            }
        by_key[key]["clicks"] += int(r.get("clicks", 0) or 0)
        by_key[key]["signups"] += int(r.get("signups", 0) or 0)

    results = []
    for m in by_key.values():
        ctr = m["clicks"] * 0.5 if m["clicks"] > 0 else 0
        conv = (m["signups"] / m["clicks"] * 100) if m["clicks"] > 0 else 0
        m["ctr"] = round(ctr, 2)
        m["conversion_rate"] = round(conv, 2)
        results.append(m)

        await db.upsert_performance(
            content_id=m["content_id"],
            platform=m["platform"],
            impressions=0,
            clicks=m["clicks"],
            signups=m["signups"],
            ctr=m["ctr"],
            conversion_rate=m["conversion_rate"],
        )

    log.info("Computed metrics for {} content-platform pairs", len(results))
    return results
