from __future__ import annotations

import numpy as np

from src.config import get_blacklist, settings
from src.storage import database as db
from src.storage.models import Priority, ScoredTopic
from loguru import logger as log

VECTOR_DEDUP_THRESHOLD = 0.85


def _is_blacklisted(title: str, blacklist: list[str]) -> bool:
    lower = title.lower()
    return any(kw in lower for kw in blacklist)


def _cosine_similarity(a: list[float], b: list[float]) -> float:
    va, vb = np.array(a), np.array(b)
    denom = np.linalg.norm(va) * np.linalg.norm(vb)
    if denom == 0:
        return 0.0
    return float(np.dot(va, vb) / denom)


async def _vector_dedup_cross_run(
    topics: list[ScoredTopic],
    embeddings: dict[str, list[float]],
    exclude_batch: str = "",
) -> list[ScoredTopic]:
    """Drop topics that are too similar to previously published fused topics in DB."""
    kept: list[ScoredTopic] = []
    for t in topics:
        emb = embeddings.get(t.title.lower())
        if emb is None:
            kept.append(t)
            continue
        similar = await db.find_similar_fused(
            emb, threshold=VECTOR_DEDUP_THRESHOLD, days=30, exclude_batch=exclude_batch,
        )
        if similar:
            best = similar[0]
            log.info("Vector cross-run dedup dropped '{}' (similar to '{}', sim={:.3f})",
                     t.title, best["title"], best["similarity"])
        else:
            kept.append(t)
    return kept


def _vector_dedup_intra_batch(
    topics: list[ScoredTopic],
    embeddings: dict[str, list[float]],
) -> list[ScoredTopic]:
    """Drop topics that are too similar to each other within the current batch."""
    kept: list[ScoredTopic] = []
    kept_embs: list[list[float]] = []
    for t in topics:
        emb = embeddings.get(t.title.lower())
        if emb is None:
            kept.append(t)
            continue
        is_dup = False
        for existing_emb in kept_embs:
            if _cosine_similarity(emb, existing_emb) >= VECTOR_DEDUP_THRESHOLD:
                is_dup = True
                break
        if is_dup:
            log.info("Vector intra-batch dedup dropped: '{}'", t.title)
        else:
            kept.append(t)
            kept_embs.append(emb)
    return kept


async def filter_and_prioritize(
    topics: list[ScoredTopic],
    existing_titles: set[str] | None = None,
    embeddings: dict[str, list[float]] | None = None,
    batch_id: str = "",
) -> list[ScoredTopic]:
    """Filter WRITE topics, remove duplicates/blacklisted, assign priority."""
    blacklist = get_blacklist()
    existing = existing_titles or set()
    emb_map = embeddings or {}

    writable = []
    for t in topics:
        if t.decision != "WRITE" or t.is_duplicate:
            continue
        if _is_blacklisted(t.title, blacklist):
            log.info("Blacklisted: '{}'", t.title)
            continue
        if t.title.lower() in existing:
            log.info("Already exists in DB: '{}'", t.title)
            continue
        writable.append(t)

    for t in writable:
        if t.viral_score >= settings.viral_threshold and t.score >= 8:
            t.priority = Priority.high
        elif t.score >= settings.score_threshold:
            t.priority = Priority.medium
        else:
            t.priority = Priority.low

    writable.sort(key=lambda t: (
        0 if t.priority == Priority.high else 1 if t.priority == Priority.medium else 2,
        -t.score,
    ))

    pre_dedup = len(writable)
    if emb_map:
        writable = _vector_dedup_intra_batch(writable, emb_map)
        writable = await _vector_dedup_cross_run(writable, emb_map, exclude_batch=batch_id)
    post_dedup = len(writable)

    log.info(
        "Filtered: {} writable topics (dropped {} vector-dups, high={}, medium={}, low={}) from {} total",
        len(writable),
        pre_dedup - post_dedup,
        sum(1 for t in writable if t.priority == Priority.high),
        sum(1 for t in writable if t.priority == Priority.medium),
        sum(1 for t in writable if t.priority == Priority.low),
        len(topics),
    )
    return writable
