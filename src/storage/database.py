from __future__ import annotations

import enum as _enum
import json
import uuid as _uuid
from decimal import Decimal
from typing import Any

from sqlalchemy import func, insert, select, text, update
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession, async_sessionmaker, create_async_engine

from src.config import settings
from src.storage.models import (
    ContentRow,
    ContentStatus,
    FusedTopicRow,
    PerformanceRow,
    PublishLogRow,
    TopicRow,
)


# ── Engine / Session ────────────────────────────────────────────

_engine: AsyncEngine | None = None
_session_factory: async_sessionmaker[AsyncSession] | None = None


async def init_db() -> None:
    global _engine, _session_factory
    url = settings.dsn.replace("postgresql://", "postgresql+asyncpg://")
    _engine = create_async_engine(url, pool_size=10, pool_pre_ping=True)
    _session_factory = async_sessionmaker(_engine, expire_on_commit=False)


async def close_db() -> None:
    global _engine, _session_factory
    if _engine:
        await _engine.dispose()
        _engine = None
        _session_factory = None


def get_session() -> AsyncSession:
    if _session_factory is None:
        raise RuntimeError("Database not initialized — call init_db() first")
    return _session_factory()


# ── Helpers ─────────────────────────────────────────────────────

def _vec_literal(emb: list[float] | Any) -> str:
    """Serialize an embedding to a PostgreSQL vector literal for text() queries."""
    if hasattr(emb, "tolist"):
        emb = emb.tolist()
    return "[" + ",".join(str(x) for x in emb) + "]"


def _to_dict(row: Any) -> dict:
    """Convert an ORM model instance to a plain dict."""
    d: dict[str, Any] = {}
    for c in row.__class__.__table__.columns:
        val = getattr(row, c.key)
        if isinstance(val, _enum.Enum):
            val = val.value
        elif isinstance(val, Decimal):
            val = float(val)
        d[c.name] = val
    return d


# ── Signals / Topics ───────────────────────────────────────────

async def fetch_recent_signals(days: int = 7, exclude_batch: str = "") -> list[dict]:
    async with get_session() as session:
        result = await session.execute(
            text("""
                SELECT source, title, url, engagement, viral_score, subreddit,
                       batch_id::text, fetched_at,
                       COUNT(*) OVER (PARTITION BY LOWER(title)) AS occurrence_count
                FROM topics
                WHERE fetched_at > NOW() - :days * INTERVAL '1 day'
                  AND (:exclude = '' OR batch_id::text != :exclude)
                ORDER BY fetched_at DESC
            """),
            {"days": days, "exclude": exclude_batch},
        )
        return [
            {
                "source": r["source"],
                "title": r["title"],
                "url": r["url"] or "",
                "engagement": int(r["engagement"]),
                "viral_score": float(r["viral_score"]),
                "subreddit": r["subreddit"],
                "occurrence_count": int(r["occurrence_count"]),
            }
            for r in result.mappings().all()
        ]


async def insert_signals(signals: list[dict], batch_id: str) -> int:
    if not signals:
        return 0
    async with get_session() as session:
        rows = [
            {
                "source": s.get("source", "unknown"),
                "title": s.get("title", ""),
                "url": s.get("url", ""),
                "engagement": int(s.get("engagement", 0)),
                "viral_score": float(s.get("viral_score", 0)),
                "subreddit": s.get("subreddit"),
                "batch_id": _uuid.UUID(batch_id),
            }
            for s in signals
        ]
        await session.execute(insert(TopicRow), rows)
        await session.commit()
        return len(rows)


# ── Fused Topics (AI-generated) ────────────────────────────────

async def insert_fused_topics(
    topics: list[dict],
    embeddings: list[list[float]],
    batch_id: str,
) -> dict[str, int]:
    """Insert AI-generated fused topics with embeddings.

    Returns a mapping of lowercase title -> fused_topics.id.
    """
    async with get_session() as session:
        title_to_id: dict[str, int] = {}
        bid = _uuid.UUID(batch_id)
        for t, emb in zip(topics, embeddings):
            title = t.get("title", "")
            result = await session.execute(
                insert(FusedTopicRow)
                .values(
                    title=title,
                    embedding=emb,
                    signal_types=t.get("signal_types", []),
                    reasoning=t.get("reasoning", ""),
                    suggested_angle=t.get("suggested_angle", ""),
                    angles=t.get("angles", {}),
                    source_urls=t.get("source_urls", []),
                    source_queries=t.get("source_queries", []),
                    viral_score=float(t.get("viral_score", 0)),
                    seo_potential=float(t.get("seo_potential", 0)),
                    batch_id=bid,
                )
                .returning(FusedTopicRow.id)
            )
            title_to_id[title.lower()] = result.scalar_one()
        await session.commit()
        return title_to_id


async def update_fused_topic_scores(scored_topics: list, batch_id: str) -> int:
    """Update fused topics with AI scores, decisions, and clusters after scoring."""
    async with get_session() as session:
        count = 0
        for t in scored_topics:
            title = t.title if hasattr(t, "title") else t.get("title", "")
            await session.execute(
                text("""
                    UPDATE fused_topics
                    SET ai_score = :score, decision = :decision, cluster = :cluster,
                        suggested_angle = :angle, priority = CAST(:priority AS priority_level),
                        is_duplicate = :is_dup
                    WHERE batch_id = CAST(:bid AS uuid) AND LOWER(title) = LOWER(:title)
                """),
                {
                    "score": float(t.score if hasattr(t, "score") else 0),
                    "decision": t.decision if hasattr(t, "decision") else "IGNORE",
                    "cluster": t.cluster if hasattr(t, "cluster") else "other",
                    "angle": t.suggested_angle if hasattr(t, "suggested_angle") else "",
                    "priority": (
                        t.priority.value
                        if hasattr(t, "priority") and hasattr(t.priority, "value")
                        else "medium"
                    ),
                    "is_dup": t.is_duplicate if hasattr(t, "is_duplicate") else False,
                    "bid": batch_id,
                    "title": title,
                },
            )
            count += 1
        await session.commit()
        return count


async def find_similar_fused(
    embedding: list[float],
    threshold: float = 0.85,
    days: int = 30,
    limit: int = 5,
    exclude_batch: str = "",
) -> list[dict]:
    """Find fused topics whose embedding is within cosine similarity threshold."""
    async with get_session() as session:
        result = await session.execute(
            text("""
                SELECT title, 1 - (embedding <=> CAST(:vec AS vector)) AS similarity
                FROM fused_topics
                WHERE created_at > NOW() - :days * INTERVAL '1 day'
                  AND embedding IS NOT NULL
                  AND (:exclude = '' OR batch_id::text != :exclude)
                ORDER BY embedding <=> CAST(:vec AS vector)
                LIMIT :lim
            """),
            {"vec": _vec_literal(embedding), "days": days, "lim": limit, "exclude": exclude_batch},
        )
        return [
            {"title": r["title"], "similarity": float(r["similarity"])}
            for r in result.mappings().all()
            if float(r["similarity"]) >= threshold
        ]


async def find_similar_fused_batch(
    embeddings: list[list[float]],
    threshold: float = 0.85,
    days: int = 30,
) -> list[list[dict]]:
    """Check each embedding against recent fused topics for duplicates."""
    results = []
    for emb in embeddings:
        similar = await find_similar_fused(emb, threshold=threshold, days=days)
        results.append(similar)
    return results


# ── Content CRUD ───────────────────────────────────────────────

async def find_similar_content(
    embedding: list[float],
    threshold: float = 0.85,
    days: int = 60,
) -> dict | None:
    """Check if a semantically similar article already exists in the content table."""
    async with get_session() as session:
        result = await session.execute(
            text("""
                SELECT content_id, title, 1 - (title_embedding <=> CAST(:vec AS vector)) AS similarity
                FROM content
                WHERE created_at > NOW() - :days * INTERVAL '1 day'
                  AND title_embedding IS NOT NULL
                ORDER BY title_embedding <=> CAST(:vec AS vector)
                LIMIT 1
            """),
            {"vec": _vec_literal(embedding), "days": days},
        )
        row = result.mappings().first()
        if row and float(row["similarity"]) >= threshold:
            return {
                "content_id": row["content_id"],
                "title": row["title"],
                "similarity": float(row["similarity"]),
            }
        return None


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
    social_posts_variant_b: dict,
    cta_a: str,
    cta_b: str,
    outline: list[str],
    suggested_angle: str,
    priority: str,
    image_url: str = "",
    wechat_article: str = "",
    title_embedding: list[float] | None = None,
    fused_topic_id: int | None = None,
) -> None:
    async with get_session() as session:
        stmt = (
            pg_insert(ContentRow)
            .values(
                content_id=content_id,
                fused_topic_id=fused_topic_id,
                title=title,
                title_embedding=title_embedding,
                cluster=cluster,
                score=score,
                article_html=article_html,
                medium_article=medium_article,
                wechat_article=wechat_article or None,
                seo_keywords=seo_keywords,
                meta_description=meta_description,
                social_posts=social_posts,
                social_posts_variant_b=social_posts_variant_b,
                cta_variant_a=cta_a,
                cta_variant_b=cta_b,
                outline=outline,
                suggested_angle=suggested_angle,
                priority=priority,
                image_url=image_url,
                status="draft",
            )
            .on_conflict_do_nothing(index_elements=["content_id"])
        )
        await session.execute(stmt)
        await session.commit()


async def update_content_status(content_id: str, status: str) -> None:
    async with get_session() as session:
        values: dict[str, Any] = {"status": status}
        if status == "approved":
            values["approved_at"] = func.now()
        await session.execute(
            update(ContentRow).where(ContentRow.content_id == content_id).values(**values)
        )
        await session.commit()


async def insert_publish_log(
    content_id: str,
    platform: str,
    url: str,
    cta_variant: str,
    post_body: str = "",
) -> None:
    async with get_session() as session:
        await session.execute(
            insert(PublishLogRow).values(
                content_id=content_id,
                platform=platform,
                published_url=url,
                cta_variant=cta_variant,
                post_body=post_body,
            )
        )
        await session.commit()


async def upsert_performance(
    content_id: str,
    platform: str,
    impressions: int,
    clicks: int,
    signups: int,
    ctr: float,
    conversion_rate: float,
) -> None:
    async with get_session() as session:
        stmt = pg_insert(PerformanceRow).values(
            content_id=content_id,
            platform=platform,
            impressions=impressions,
            clicks=clicks,
            signups=signups,
            ctr=ctr,
            conversion_rate=conversion_rate,
        )
        stmt = stmt.on_conflict_do_update(
            constraint="uq_perf_content_platform_period",
            set_={
                "impressions": stmt.excluded.impressions,
                "clicks": stmt.excluded.clicks,
                "signups": stmt.excluded.signups,
                "ctr": stmt.excluded.ctr,
                "conversion_rate": stmt.excluded.conversion_rate,
                "measured_at": func.now(),
            },
        )
        await session.execute(stmt)
        await session.commit()


# ── Queries ────────────────────────────────────────────────────

async def fetch_cluster_feedback() -> list[dict]:
    async with get_session() as session:
        result = await session.execute(
            text("""
                SELECT c.cluster, COUNT(*) AS total_posts,
                       COALESCE(AVG(p.ctr),0) AS avg_ctr,
                       COALESCE(AVG(p.conversion_rate),0) AS avg_conversion
                FROM content c
                LEFT JOIN performance p ON c.content_id = p.content_id
                WHERE c.status IN ('approved','published')
                  AND c.created_at > NOW() - INTERVAL '30 days'
                GROUP BY c.cluster
            """)
        )
        return [dict(r) for r in result.mappings().all()]


async def fetch_top_performers(limit: int = 10) -> list[dict]:
    async with get_session() as session:
        result = await session.execute(
            text("""
                SELECT c.content_id, c.title, c.cluster, c.suggested_angle,
                       COALESCE(c.seo_keywords, '[]') AS seo_keywords,
                       ROUND(AVG(p.ctr)::numeric, 2) AS avg_ctr,
                       ROUND(AVG(p.conversion_rate)::numeric, 2) AS avg_conv,
                       SUM(p.clicks) AS total_clicks,
                       SUM(p.signups) AS total_signups,
                       COUNT(DISTINCT pl.platform) AS platforms_published
                FROM content c
                JOIN performance p ON c.content_id = p.content_id
                JOIN publish_logs pl ON c.content_id = pl.content_id
                WHERE c.status IN ('approved','published')
                  AND (p.ctr > 1.5 OR p.conversion_rate > 1.0)
                  AND c.created_at > NOW() - INTERVAL '60 days'
                GROUP BY c.content_id, c.title, c.cluster, c.suggested_angle, c.seo_keywords
                ORDER BY AVG(p.conversion_rate) DESC, AVG(p.ctr) DESC
                LIMIT :lim
            """),
            {"lim": limit},
        )
        return [dict(r) for r in result.mappings().all()]


async def fetch_recent_publishes(days: int = 7) -> list[dict]:
    async with get_session() as session:
        result = await session.execute(
            text("""
                SELECT pl.content_id, c.title, c.cluster, c.score,
                       pl.platform, pl.cta_variant, pl.published_at,
                       COALESCE(p.ctr,0) AS ctr,
                       COALESCE(p.conversion_rate,0) AS conversion_rate,
                       COALESCE(p.clicks,0) AS clicks,
                       COALESCE(p.signups,0) AS signups
                FROM publish_logs pl
                JOIN content c ON pl.content_id = c.content_id
                LEFT JOIN performance p
                    ON pl.content_id = p.content_id AND pl.platform = p.platform
                WHERE pl.published_at > NOW() - :days * INTERVAL '1 day'
                ORDER BY pl.published_at DESC
            """),
            {"days": days},
        )
        return [dict(r) for r in result.mappings().all()]


async def fetch_low_ctr_content(threshold: float = 1.0, limit: int = 5) -> list[dict]:
    async with get_session() as session:
        result = await session.execute(
            text("""
                SELECT c.content_id, c.title, c.cluster, c.article_html,
                       c.cta_variant_a, c.cta_variant_b,
                       AVG(p.ctr) AS avg_ctr
                FROM content c
                JOIN performance p ON c.content_id = p.content_id
                WHERE c.status = 'approved' AND p.ctr < :threshold
                  AND c.created_at > NOW() - INTERVAL '30 days'
                GROUP BY c.content_id, c.title, c.cluster, c.article_html,
                         c.cta_variant_a, c.cta_variant_b
                ORDER BY AVG(p.ctr) ASC
                LIMIT :lim
            """),
            {"threshold": threshold, "lim": limit},
        )
        return [dict(r) for r in result.mappings().all()]


async def update_regenerated(
    content_id: str,
    article_html: str,
    social_posts: dict,
    title: str | None = None,
) -> None:
    async with get_session() as session:
        stmt = (
            update(ContentRow)
            .where(ContentRow.content_id == content_id)
            .values(
                article_html=article_html,
                social_posts=social_posts,
                iteration_count=ContentRow.iteration_count + 1,
            )
        )
        if title:
            stmt = stmt.values(title=title)
        await session.execute(stmt)
        await session.commit()


async def get_pending_approval(content_id: str) -> dict | None:
    async with get_session() as session:
        result = await session.execute(
            select(ContentRow).where(
                ContentRow.content_id == content_id,
                ContentRow.status == ContentStatus.draft,
            )
        )
        row = result.scalar_one_or_none()
        return _to_dict(row) if row else None


async def title_exists(title: str, days: int = 30) -> bool:
    async with get_session() as session:
        result = await session.execute(
            text("""
                SELECT 1 FROM content
                WHERE LOWER(title) = LOWER(:title)
                  AND created_at > NOW() - :days * INTERVAL '1 day'
                LIMIT 1
            """),
            {"title": title, "days": days},
        )
        return result.first() is not None


async def fetch_recent_titles(days: int = 30) -> set[str]:
    async with get_session() as session:
        result = await session.execute(
            text(
                "SELECT LOWER(title) AS t FROM content"
                " WHERE created_at > NOW() - :days * INTERVAL '1 day'"
            ),
            {"days": days},
        )
        return {r[0] for r in result.all()}


async def fetch_ab_results() -> list[dict]:
    async with get_session() as session:
        result = await session.execute(
            text("""
                SELECT pl.cta_variant,
                       COUNT(*) AS total_publishes,
                       COALESCE(AVG(p.ctr), 0) AS avg_ctr,
                       COALESCE(AVG(p.conversion_rate), 0) AS avg_conv,
                       COALESCE(SUM(p.clicks), 0) AS total_clicks,
                       COALESCE(SUM(p.signups), 0) AS total_signups
                FROM publish_logs pl
                LEFT JOIN performance p
                    ON pl.content_id = p.content_id AND pl.platform = p.platform
                WHERE pl.published_at > NOW() - INTERVAL '30 days'
                GROUP BY pl.cta_variant
            """)
        )
        return [dict(r) for r in result.mappings().all()]


async def fetch_content(content_id: str) -> dict | None:
    """Fetch a full content row as a dict, or None if not found."""
    async with get_session() as session:
        result = await session.execute(
            select(ContentRow).where(ContentRow.content_id == content_id)
        )
        row = result.scalar_one_or_none()
        return _to_dict(row) if row else None


async def ping() -> bool:
    try:
        async with get_session() as session:
            await session.execute(text("SELECT 1"))
        return True
    except Exception:
        return False
