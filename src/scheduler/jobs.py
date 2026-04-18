from __future__ import annotations

import asyncio
import uuid

from src.approval.telegram_bot import send_for_approval
from src.config import settings
from src.content.featured_image import generate_featured
from src.content.generator import generate
from src.content.humanizer import humanize
from src.content.image_enricher import enrich
from src.feedback.ab_analyzer import analyze_ab_results, get_preferred_variant
from src.feedback.content_iterator import iterate_low_ctr
from src.feedback.dashboard_export import export_dashboard
from src.feedback.metrics_collector import collect_and_compute
from src.ingestors import ALL_INGESTORS
from src.ingestors.top_performers import fetch_top_performers
from src.pipeline.content_filter import filter_and_prioritize
from src.pipeline.normalizer import normalize_all
from src.pipeline.score_adjuster import adjust
from src.pipeline.signal_fusion import fuse
from src.pipeline.topic_expander import expand
from src.pipeline.topic_scorer import score
from src.pipeline.viral_scorer import score as viral_score
from src.publishers.base import PublishResult
from src.publishers.facebook import FacebookPublisher
from src.publishers.linkedin import LinkedInPublisher
from src.publishers.medium import MediumPublisher
from src.publishers.website import WebsitePublisher
from src.storage import database as db
from loguru import logger as log


PUBLISHERS = [WebsitePublisher(), MediumPublisher(), LinkedInPublisher(), FacebookPublisher()]


async def main_pipeline() -> None:
    """Main content generation pipeline — runs every N hours."""
    log.info("========== Starting main pipeline ==========")

    try:
        # 1. Parallel data ingestion
        log.info("[1/8] Fetching signals from {} sources...", len(ALL_INGESTORS))
        raw_batches = await asyncio.gather(
            *[fn() for fn in ALL_INGESTORS],
            return_exceptions=True,
        )
        for i, batch in enumerate(raw_batches):
            if isinstance(batch, Exception):
                log.warning("Ingestor {} failed: {}", i, batch)
        signal_batches = [b for b in raw_batches if isinstance(b, list)]

        # 2. Normalize + deduplicate
        log.info("[2/8] Normalizing signals...")
        signals = normalize_all(signal_batches)

        # 3. Viral scoring
        log.info("[3/8] Scoring virality...")
        scored_signals = viral_score(signals)

        # Persist raw signals to DB
        batch_id = str(uuid.uuid4())
        saved = await db.insert_signals(scored_signals, batch_id)
        log.info("Saved {} signals to DB (batch={})", saved, batch_id[:8])

        # 4. Signal fusion (GPT-4o)
        log.info("[4/8] Fusing signals into hybrid topics...")
        fused_topics = await fuse(scored_signals)

        # 5. Content flywheel — derive from top performers
        log.info("[5/8] Expanding from top performers...")
        performers = await fetch_top_performers()
        derived_topics = await expand(performers)
        all_topics = fused_topics + derived_topics
        log.info("Total topics: {} fused + {} derived = {}", len(fused_topics), len(derived_topics), len(all_topics))

        # 6. AI scoring + cluster adjustment
        log.info("[6/8] Scoring {} topics...", len(all_topics))
        cluster_feedback = await db.fetch_cluster_feedback()
        feedback_dicts = [dict(r) for r in cluster_feedback]
        scored_topics = await score(all_topics, feedback_dicts)

        cluster_perf = {}
        for f in feedback_dicts:
            if f.get("cluster"):
                cluster_perf[f["cluster"]] = {
                    "avg_ctr": float(f.get("avg_ctr", 0)),
                    "avg_conversion": float(f.get("avg_conversion", 0)),
                }
        scored_topics = adjust(scored_topics, cluster_perf)

        # Persist fused+scored topics to DB
        fused_saved = await db.insert_signals(
            [{"source": "fused", "title": t.title, "engagement": 0,
              "viral_score": t.viral_score} for t in scored_topics],
            batch_id,
        )
        updated = await db.update_topic_scores(scored_topics, batch_id)
        log.info("Saved {} fused topics, updated {} scores", fused_saved, updated)

        # 7. Filter, deduplicate against DB, apply blacklist
        log.info("[7/8] Filtering...")
        existing_titles = await db.fetch_recent_titles(days=30)
        writable = filter_and_prioritize(scored_topics, existing_titles)
        log.info("{} topics to write (after DB dedup + blacklist)", len(writable))

        # 8. Generate content for each topic
        log.info("[8/8] Generating content for {} topics...", min(len(writable), 8))
        success_count = 0
        for topic in writable[:8]:
            try:
                pkg = await generate(topic)
                pkg = await humanize(pkg)
                pkg = await enrich(pkg)
                pkg = await generate_featured(pkg)

                await db.insert_draft(
                    content_id=pkg.content_id,
                    title=pkg.article_title,
                    cluster=topic.cluster,
                    score=topic.score,
                    article_html=pkg.article_html,
                    medium_article=pkg.medium_article,
                    seo_keywords=pkg.seo_keywords,
                    meta_description=pkg.meta_description,
                    social_posts=pkg.social_posts,
                    social_posts_variant_b=pkg.social_posts_variant_b,
                    cta_a=pkg.cta_variant_a,
                    cta_b=pkg.cta_variant_b,
                    outline=pkg.outline,
                    suggested_angle=topic.suggested_angle,
                    priority=topic.priority.value,
                    image_url=pkg.featured_image_url,
                )

                if settings.auto_approve:
                    await db.update_content_status(pkg.content_id, "approved")
                    log.info("✓ Auto-approved: '{}' (score={:.1f}, cluster={})",
                             pkg.article_title, topic.score, topic.cluster)
                    await publish_approved(pkg.content_id)
                else:
                    await send_for_approval(pkg)
                    log.info("✓ Queued for approval: '{}' (score={:.1f}, cluster={})",
                             pkg.article_title, topic.score, topic.cluster)
                success_count += 1
            except Exception as exc:
                log.error("✗ Failed topic '{}': {}", topic.title, exc, exc_info=True)

        log.info("========== Pipeline complete: {}/{} articles generated ==========",
                 success_count, min(len(writable), 8))
    except Exception as exc:
        log.error("Pipeline failed: {}", exc, exc_info=True)


async def publish_approved(content_id: str) -> None:
    """Called when content is approved via Telegram — publish to all platforms."""
    log.info("Publishing approved content: {}", content_id)
    row = await db.fetchrow(
        "SELECT * FROM content WHERE content_id = $1", content_id,
    )
    if not row:
        log.warning("Content {} not found", content_id)
        return

    import json
    from src.storage.models import ContentPackage

    social = row.get("social_posts", "{}")
    if isinstance(social, str):
        try:
            social = json.loads(social)
        except json.JSONDecodeError:
            social = {}

    social_b = row.get("social_posts_variant_b", "{}")
    if isinstance(social_b, str):
        try:
            social_b = json.loads(social_b)
        except json.JSONDecodeError:
            social_b = {}

    keywords = row.get("seo_keywords", "[]")
    if isinstance(keywords, str):
        try:
            keywords = json.loads(keywords)
        except json.JSONDecodeError:
            keywords = []

    pkg = ContentPackage(
        content_id=content_id,
        article_title=row["title"],
        article_html=row.get("article_html", ""),
        medium_article=row.get("medium_article", ""),
        social_posts=social if isinstance(social, dict) else {},
        social_posts_variant_b=social_b if isinstance(social_b, dict) else {},
        seo_keywords=keywords if isinstance(keywords, list) else [],
        meta_description=row.get("meta_description", ""),
        cta_variant_a=row.get("cta_variant_a", ""),
        cta_variant_b=row.get("cta_variant_b", ""),
        featured_image_url=row.get("image_url", ""),
    )

    cta_variant = await get_preferred_variant()
    log.info("Using CTA variant '{}' (A/B winner)", cta_variant)

    results: list[PublishResult | Exception] = await asyncio.gather(
        *[p.publish(pkg, cta_variant) for p in PUBLISHERS],
        return_exceptions=True,
    )

    published = 0
    for r in results:
        if isinstance(r, Exception):
            log.error("Publish error: {}", r)
            continue
        if r.success:
            await db.insert_publish_log(
                content_id, r.platform, r.url, cta_variant, r.post_body,
            )
            published += 1
        else:
            log.warning("Publish failed on {}: {}", r.platform, r.error)

    await db.update_content_status(content_id, "published")
    log.info("Published {} to {}/{} platforms", content_id, published, len(PUBLISHERS))


async def daily_metrics() -> None:
    """Daily job: collect metrics, A/B analysis, iterate low CTR, export dashboard."""
    log.info("========== Starting daily metrics ==========")
    try:
        metrics = await collect_and_compute(days=7)
        log.info("Computed metrics for {} content-platform pairs", len(metrics))

        ab_result = await analyze_ab_results()
        log.info("A/B analysis: winner={}, confidence={}", ab_result["winner"], ab_result["confidence"])

        regen_count = await iterate_low_ctr(ctr_threshold=1.0, limit=5)
        log.info("Regenerated {} low-CTR articles", regen_count)

        await export_dashboard()

        log.info("========== Daily metrics complete ==========")
    except Exception as exc:
        log.error("Daily metrics failed: {}", exc, exc_info=True)
