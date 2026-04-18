from __future__ import annotations

import json

from src.storage import database as db
from src.utils.ai_client import chat_claude
from loguru import logger as log


REGEN_SYSTEM = (
    "You are a content optimizer for 'mockreal'. Rewrite the given article's title, "
    "opening hook, CTA, and social posts to improve click-through rate.\n\n"
    "Keep the same core topic and HTML structure. Only change: title, first paragraph, "
    "CTA text, and social posts.\n\n"
    'Return JSON: {"article_title":"...","article_html":"...","social_posts":{...}}'
)


async def iterate_low_ctr(ctr_threshold: float = 1.0, limit: int = 5) -> int:
    """Find low-CTR content and regenerate hooks/CTAs."""
    rows = await db.fetch_low_ctr_content(threshold=ctr_threshold, limit=limit)
    if not rows:
        log.info("No low-CTR content to iterate")
        return 0

    regen_count = 0
    for row in rows:
        try:
            content_id = row["content_id"]
            user_msg = (
                f"Improve this underperforming article (CTR: {float(row['avg_ctr']):.1f}%):\n\n"
                f"Title: {row['title']}\n"
                f"Cluster: {row['cluster']}\n"
                f"HTML (first 2000 chars):\n{row['article_html'][:2000]}"
            )

            raw = await chat_claude(
                user_message=user_msg,
                system=REGEN_SYSTEM,
                max_tokens=6000,
                temperature=0.7,
            )

            cleaned = raw.strip()
            if cleaned.startswith("```"):
                cleaned = cleaned.split("\n", 1)[-1].rsplit("```", 1)[0]
            data = json.loads(cleaned)

            new_html = data.get("article_html", row["article_html"])
            new_social = data.get("social_posts", {})
            new_title = data.get("article_title")

            await db.update_regenerated(content_id, new_html, new_social, title=new_title)
            regen_count += 1
            log.info("Regenerated content {} ('{}')", content_id, row["title"][:50])
        except Exception as exc:
            log.warning("Failed to regenerate {}: {}", row.get("content_id", "?"), exc)

    log.info("Regenerated {}/{} low-CTR articles", regen_count, len(rows))
    return regen_count
