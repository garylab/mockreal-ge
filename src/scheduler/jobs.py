from __future__ import annotations

import asyncio
import uuid

from src.approval.telegram_bot import send_for_approval
from src.config import get_seed_keywords, settings
from src.content.featured_image import generate_featured
from src.content.generator import generate
from src.content.humanizer import humanize
from src.content.image_enricher import enrich
from src.content.researcher import research_topic
from src.content.wechat_converter import convert_to_wechat
from src.feedback.ab_analyzer import analyze_ab_results, get_preferred_variant
from src.feedback.content_iterator import iterate_low_ctr
from src.feedback.dashboard_export import export_dashboard
from src.feedback.metrics_collector import collect_and_compute
from src.publishers.base import PublishResult
from src.publishers.facebook import FacebookPublisher
from src.publishers.linkedin import LinkedInPublisher
from src.publishers.medium import MediumPublisher
from src.publishers.wechat import WechatPublisher
from src.publishers.website import WebsitePublisher
from src.storage import database as db
from src.storage.models import ScoredTopic
from src.utils.ai_client import embed_text
from loguru import logger as log


PUBLISHERS = [WebsitePublisher(), MediumPublisher(), LinkedInPublisher(), FacebookPublisher(), WechatPublisher()]


async def main_pipeline() -> None:
    """Intent-driven content production pipeline.

    1. Pick the highest-priority active cluster
    2. Pick uncovered intents (pillar first, then supporting)
    3. Research each intent (Search + News + Scholar)
    4. Generate, humanize, enrich, publish
    5. Mark intent as covered
    """
    log.info("========== Starting intent-driven pipeline ==========")

    try:
        # 1. Find clusters with pending intents
        active_clusters = await db.fetch_active_clusters()
        if not active_clusters:
            log.info("No active clusters with pending intents — run intent mining first")
            return

        log.info("[1/4] Found {} active clusters with pending intents", len(active_clusters))

        cap = settings.max_articles_per_run
        success_count = 0
        intents_to_write: list[tuple[dict, dict]] = []  # (intent, cluster)

        # 2. Collect intents across clusters, prioritizing pillar intents
        for cluster in active_clusters:
            if len(intents_to_write) >= cap:
                break
            pending = await db.fetch_cluster_intents(cluster["id"], status="pending")
            if not pending:
                await db.mark_cluster_covered(cluster["id"])
                log.info("Cluster '{}' fully covered", cluster["name"])
                continue

            for intent in pending:
                if len(intents_to_write) >= cap:
                    break
                intents_to_write.append((intent, cluster))

        if not intents_to_write:
            log.info("No pending intents to write — all clusters covered")
            return

        log.info("[2/4] Selected {} intents to write (cap={})", len(intents_to_write), cap)
        for intent, cluster in intents_to_write:
            pillar_tag = " [PILLAR]" if intent.get("is_pillar") else ""
            log.info("  → '{}' (cluster: {}){}", intent["title"], cluster["name"], pillar_tag)

        # 3. Generate content for each intent
        log.info("[3/4] Generating content...")
        for intent, cluster in intents_to_write:
            try:
                # Duplicate check against existing content
                title_emb = await embed_text(intent["title"])
                if title_emb:
                    existing = await db.find_similar_content(title_emb, threshold=0.85, days=60)
                    if existing:
                        log.warning("Skipping '{}' — too similar to '{}' (sim={:.3f})",
                                    intent["title"], existing["title"], existing["similarity"])
                        await db.mark_intent_covered(intent["id"], existing["content_id"])
                        continue

                # Research: Google Search + News + Scholar
                research = await research_topic(intent["title"])

                # Build a ScoredTopic from the intent for the generator
                source_urls = [s["url"] for s in research.get("sources", []) if s.get("url")]
                topic = ScoredTopic(
                    title=intent["title"],
                    source="intent",
                    score=float(intent.get("priority_score", 7)),
                    decision="WRITE",
                    suggested_angle="",
                    cluster=cluster["slug"],
                    source_urls=source_urls,
                )

                pkg = await generate(topic, research=research)
                pkg.source_images = research.get("source_images", [])
                pkg = await humanize(pkg)
                pkg = await enrich(pkg)
                pkg = await generate_featured(pkg)
                pkg = await convert_to_wechat(pkg)

                final_emb = await embed_text(pkg.article_title)

                raw_score = float(intent.get("priority_score", 7))
                content_score = min(raw_score / 125, 10.0)  # normalize to 0-10

                await db.insert_draft(
                    content_id=pkg.content_id,
                    title=pkg.article_title,
                    cluster=cluster["slug"],
                    score=round(content_score, 1),
                    article_html=pkg.article_html,
                    medium_article=pkg.medium_article,
                    wechat_article=pkg.wechat_article,
                    seo_keywords=pkg.seo_keywords,
                    meta_description=pkg.meta_description,
                    social_posts=pkg.social_posts,
                    social_posts_variant_b=pkg.social_posts_variant_b,
                    cta_a=pkg.cta_variant_a,
                    cta_b=pkg.cta_variant_b,
                    outline=pkg.outline,
                    suggested_angle="",
                    priority="medium",
                    image_url=pkg.featured_image_url,
                    title_embedding=final_emb,
                    intent_id=intent["id"],
                )

                # Mark intent as covered
                await db.mark_intent_covered(intent["id"], pkg.content_id)

                if settings.auto_approve:
                    await db.update_content_status(pkg.content_id, "approved")
                    log.info("✓ Auto-approved: '{}' (intent: '{}', cluster: {})",
                             pkg.article_title, intent["title"], cluster["name"])
                    await publish_approved(pkg.content_id)
                else:
                    await send_for_approval(pkg)
                    log.info("✓ Queued for approval: '{}' (intent: '{}', cluster: {})",
                             pkg.article_title, intent["title"], cluster["name"])
                success_count += 1

            except Exception as exc:
                log.error("✗ Failed intent '{}': {}", intent["title"], exc, exc_info=True)

        # 4. Summary
        stats = await db.fetch_intent_stats()
        log.info(
            "========== Pipeline complete: {}/{} articles generated "
            "(DB: {} pending, {} covered) ==========",
            success_count, len(intents_to_write),
            stats.get("pending", 0), stats.get("covered", 0),
        )
    except Exception as exc:
        log.error("Pipeline failed: {}", exc, exc_info=True)


async def publish_approved(content_id: str) -> None:
    """Called when content is approved via Telegram — publish to all platforms."""
    log.info("Publishing approved content: {}", content_id)
    row = await db.fetch_content(content_id)
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
        wechat_article=row.get("wechat_article", ""),
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


async def growth_loop() -> None:
    """Phase 3: Expand covered clusters with deeper intents.

    For clusters where all intents are covered, mine new deeper intents
    using the cluster's pillar topic as a seed, then add them to the cluster.
    """
    from src.pipeline.intent_miner import mine_intents
    from src.pipeline.intent_clusterer import process_intents

    log.info("========== Starting growth loop ==========")
    try:
        # Find fully covered clusters
        async with db.get_session() as session:
            result = await session.execute(
                db.text("""
                    SELECT ic.id, ic.name, ic.slug, ic.pillar_intent_id
                    FROM intent_clusters ic
                    WHERE ic.status = 'active'
                      AND ic.covered_count >= ic.intent_count
                      AND ic.intent_count > 0
                    ORDER BY ic.priority_score DESC
                    LIMIT 10
                """)
            )
            covered_clusters = [dict(r) for r in result.mappings().all()]

        if not covered_clusters:
            log.info("No fully-covered clusters to expand")
            return

        log.info("Found {} fully-covered clusters to expand", len(covered_clusters))

        for cluster in covered_clusters:
            # Get the pillar intent title as the seed
            pillar_id = cluster.get("pillar_intent_id")
            if not pillar_id:
                continue

            async with db.get_session() as session:
                result = await session.execute(
                    db.text("SELECT title FROM intents WHERE id = :id"),
                    {"id": pillar_id},
                )
                row = result.mappings().first()

            if not row:
                continue

            seed = row["title"]
            log.info("Expanding cluster '{}' with seed '{}'", cluster["name"], seed)

            raw_intents = await mine_intents([seed])
            if raw_intents:
                batch_id = str(uuid.uuid4())
                summary = await process_intents(raw_intents, batch_id)
                log.info("Added {} new intents from expansion of '{}'",
                         summary.get("intents", 0), cluster["name"])

            # Mark as expanding so it doesn't get re-expanded next run
            await db.mark_cluster_covered(cluster["id"])

        log.info("========== Growth loop complete ==========")
    except Exception as exc:
        log.error("Growth loop failed: {}", exc, exc_info=True)


async def intent_mining_pipeline() -> None:
    """Mine user intents, deduplicate, cluster, and save to DB.

    Runs less frequently than content production (e.g. weekly).
    """
    from src.pipeline.intent_miner import mine_intents
    from src.pipeline.intent_clusterer import process_intents

    log.info("========== Starting intent mining pipeline ==========")
    try:
        seeds = get_seed_keywords()
        if not seeds:
            log.warning("No seed keywords configured — skipping intent mining")
            return

        batch_id = str(uuid.uuid4())
        log.info("Mining intents from {} seeds (batch={})", len(seeds), batch_id[:8])

        raw_intents = await mine_intents(seeds)
        if not raw_intents:
            log.warning("No intents mined — check API keys and seed keywords")
            return

        summary = await process_intents(raw_intents, batch_id)
        stats = await db.fetch_intent_stats()

        log.info(
            "========== Intent mining complete: {} raw → {} new intents in {} clusters "
            "(DB total: {} intents, {} pending, {} covered) ==========",
            summary["total"], summary["intents"], summary["clusters"],
            stats.get("total_intents", 0), stats.get("pending", 0), stats.get("covered", 0),
        )
    except Exception as exc:
        log.error("Intent mining failed: {}", exc, exc_info=True)


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
