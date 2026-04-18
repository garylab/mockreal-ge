from __future__ import annotations

import json
from typing import Any

import asyncpg

from src.config import settings


_pool: asyncpg.Pool | None = None


async def get_pool() -> asyncpg.Pool:
    global _pool
    if _pool is None:
        _pool = await asyncpg.create_pool(
            dsn=settings.dsn,
            min_size=2,
            max_size=10,
        )
    return _pool


async def close_pool() -> None:
    global _pool
    if _pool:
        await _pool.close()
        _pool = None


async def execute(query: str, *args: Any) -> str:
    pool = await get_pool()
    return await pool.execute(query, *args)


async def fetch(query: str, *args: Any) -> list[asyncpg.Record]:
    pool = await get_pool()
    return await pool.fetch(query, *args)


async def fetchrow(query: str, *args: Any) -> asyncpg.Record | None:
    pool = await get_pool()
    return await pool.fetchrow(query, *args)


async def fetchval(query: str, *args: Any) -> Any:
    pool = await get_pool()
    return await pool.fetchval(query, *args)


# ── Content CRUD ─────────────────────────────────────────────

async def insert_draft(
    content_id: str,
    title: str,
    cluster: str,
    score: float,
    article_html: str,
    medium_article: str,
    seo_keywords: list[str],
    meta_description: str,
    social_posts: dict,
    cta_a: str,
    cta_b: str,
    outline: list[str],
    suggested_angle: str,
    priority: str,
) -> None:
    await execute(
        """
        INSERT INTO mockreal.content
            (content_id, title, cluster, score, article_html, medium_article,
             seo_keywords, meta_description, social_posts,
             cta_variant_a, cta_variant_b, outline, suggested_angle, priority, status)
        VALUES ($1,$2,$3,$4,$5,$6,$7,$8,$9,$10,$11,$12,$13,$14,'draft')
        ON CONFLICT (content_id) DO NOTHING
        """,
        content_id, title, cluster, score, article_html, medium_article,
        json.dumps(seo_keywords), meta_description, json.dumps(social_posts),
        cta_a, cta_b, json.dumps(outline), suggested_angle, priority,
    )


async def update_content_status(content_id: str, status: str) -> None:
    extra = ", approved_at = NOW()" if status == "approved" else ""
    await execute(
        f"UPDATE mockreal.content SET status = $1{extra} WHERE content_id = $2",
        status, content_id,
    )


async def insert_publish_log(
    content_id: str, platform: str, url: str, cta_variant: str,
) -> None:
    await execute(
        """
        INSERT INTO mockreal.publish_logs (content_id, platform, url, cta_variant)
        VALUES ($1, $2, $3, $4)
        """,
        content_id, platform, url, cta_variant,
    )


async def upsert_performance(
    content_id: str, platform: str,
    impressions: int, clicks: int, signups: int,
    ctr: float, conversion_rate: float,
) -> None:
    await execute(
        """
        INSERT INTO mockreal.performance
            (content_id, platform, impressions, clicks, signups, ctr, conversion_rate)
        VALUES ($1,$2,$3,$4,$5,$6,$7)
        ON CONFLICT (content_id, platform) DO UPDATE SET
            impressions = EXCLUDED.impressions,
            clicks = EXCLUDED.clicks,
            signups = EXCLUDED.signups,
            ctr = EXCLUDED.ctr,
            conversion_rate = EXCLUDED.conversion_rate,
            measured_at = NOW()
        """,
        content_id, platform, impressions, clicks, signups, ctr, conversion_rate,
    )


# ── Queries ──────────────────────────────────────────────────

async def fetch_cluster_feedback() -> list[asyncpg.Record]:
    return await fetch(
        """
        SELECT c.cluster, COUNT(*) AS total_posts,
               COALESCE(AVG(p.ctr),0) AS avg_ctr,
               COALESCE(AVG(p.conversion_rate),0) AS avg_conversion
        FROM mockreal.content c
        LEFT JOIN mockreal.performance p ON c.content_id = p.content_id
        WHERE c.status = 'approved' AND c.created_at > NOW() - INTERVAL '30 days'
        GROUP BY c.cluster
        """
    )


async def fetch_top_performers(limit: int = 10) -> list[asyncpg.Record]:
    return await fetch(
        """
        SELECT c.content_id, c.title, c.cluster, c.suggested_angle,
               COALESCE(c.seo_keywords, '[]') AS seo_keywords,
               ROUND(AVG(p.ctr)::numeric, 2) AS avg_ctr,
               ROUND(AVG(p.conversion_rate)::numeric, 2) AS avg_conv,
               SUM(p.clicks) AS total_clicks,
               SUM(p.signups) AS total_signups,
               COUNT(DISTINCT pl.platform) AS platforms_published
        FROM mockreal.content c
        JOIN mockreal.performance p ON c.content_id = p.content_id
        JOIN mockreal.publish_logs pl ON c.content_id = pl.content_id
        WHERE c.status IN ('approved','published')
          AND (p.ctr > 1.5 OR p.conversion_rate > 1.0)
          AND c.created_at > NOW() - INTERVAL '60 days'
        GROUP BY c.content_id, c.title, c.cluster, c.suggested_angle, c.seo_keywords
        ORDER BY AVG(p.conversion_rate) DESC, AVG(p.ctr) DESC
        LIMIT $1
        """,
        limit,
    )


async def fetch_recent_publishes(days: int = 7) -> list[asyncpg.Record]:
    return await fetch(
        """
        SELECT pl.content_id, c.title, c.cluster, c.score,
               pl.platform, pl.cta_variant, pl.published_at,
               COALESCE(p.ctr,0) AS ctr,
               COALESCE(p.conversion_rate,0) AS conversion_rate,
               COALESCE(p.clicks,0) AS clicks,
               COALESCE(p.signups,0) AS signups
        FROM mockreal.publish_logs pl
        JOIN mockreal.content c ON pl.content_id = c.content_id
        LEFT JOIN mockreal.performance p
            ON pl.content_id = p.content_id AND pl.platform = p.platform
        WHERE pl.published_at > NOW() - INTERVAL '%s days'
        ORDER BY pl.published_at DESC
        """,
        days,
    )


async def fetch_low_ctr_content(threshold: float = 1.0, limit: int = 5) -> list[asyncpg.Record]:
    return await fetch(
        """
        SELECT c.content_id, c.title, c.cluster, c.article_html,
               c.cta_variant_a, c.cta_variant_b,
               AVG(p.ctr) AS avg_ctr
        FROM mockreal.content c
        JOIN mockreal.performance p ON c.content_id = p.content_id
        WHERE c.status = 'approved' AND p.ctr < $1
          AND c.created_at > NOW() - INTERVAL '30 days'
        GROUP BY c.content_id, c.title, c.cluster, c.article_html,
                 c.cta_variant_a, c.cta_variant_b
        ORDER BY AVG(p.ctr) ASC
        LIMIT $2
        """,
        threshold, limit,
    )


async def update_regenerated(content_id: str, article_html: str, social_posts: dict) -> None:
    await execute(
        """
        UPDATE mockreal.content
        SET article_html = $2, social_posts = $3, updated_at = NOW()
        WHERE content_id = $1
        """,
        content_id, article_html, json.dumps(social_posts),
    )


async def get_pending_approval(content_id: str) -> asyncpg.Record | None:
    return await fetchrow(
        "SELECT * FROM mockreal.content WHERE content_id = $1 AND status = 'draft'",
        content_id,
    )


async def title_exists(title: str, days: int = 30) -> bool:
    """Check if a similar title was already generated recently."""
    row = await fetchrow(
        """
        SELECT 1 FROM mockreal.content
        WHERE LOWER(title) = LOWER($1)
          AND created_at > NOW() - INTERVAL '%s days'
        LIMIT 1
        """,
        title, days,
    )
    return row is not None


async def fetch_recent_titles(days: int = 30) -> set[str]:
    rows = await fetch(
        "SELECT LOWER(title) AS t FROM mockreal.content WHERE created_at > NOW() - INTERVAL '%s days'",
        days,
    )
    return {r["t"] for r in rows}


async def fetch_ab_results() -> list[asyncpg.Record]:
    """Fetch A/B test results aggregated by CTA variant."""
    return await fetch(
        """
        SELECT pl.cta_variant,
               COUNT(*) AS total_publishes,
               COALESCE(AVG(p.ctr), 0) AS avg_ctr,
               COALESCE(AVG(p.conversion_rate), 0) AS avg_conv,
               COALESCE(SUM(p.clicks), 0) AS total_clicks,
               COALESCE(SUM(p.signups), 0) AS total_signups
        FROM mockreal.publish_logs pl
        LEFT JOIN mockreal.performance p
            ON pl.content_id = p.content_id AND pl.platform = p.platform
        WHERE pl.published_at > NOW() - INTERVAL '30 days'
        GROUP BY pl.cta_variant
        """
    )


async def ping() -> bool:
    try:
        await fetchval("SELECT 1")
        return True
    except Exception:
        return False
