"""Merge fresh signals with historical signals from past pipeline runs.

Recurring signals (appeared in multiple batches) get boosted scores,
making them more likely to surface as fused topics.

Uses embedding cosine similarity for matching fresh ↔ historical signals
instead of exact title matching.
"""
from __future__ import annotations

import numpy as np

from src.utils.ai_client import embed_texts
from loguru import logger as log

MATCH_SIMILARITY = 0.88
RECYCLE_SIMILARITY = 0.82


async def merge_with_history(
    fresh: list[dict],
    historical: list[dict],
    fresh_embeddings: dict[str, list[float]] | None = None,
    boost_per_occurrence: float = 1.5,
    max_boost: float = 4.0,
) -> tuple[list[dict], dict[str, list[float]]]:
    """Merge fresh signals with historical ones using embedding similarity.

    Returns (merged_signals, updated_embedding_map).

    - Recurring signals (cosine sim >= 0.88) get their viral_score boosted.
    - Historical signals not matched to any fresh signal are re-added with decay.
    - Deduplicates semantically via embeddings.
    """
    emb_map = dict(fresh_embeddings) if fresh_embeddings else {}

    if not historical:
        merged = sorted(fresh, key=lambda s: s.get("viral_score", 0), reverse=True)
        log.info("Signal memory: {} fresh + 0 historical -> {} merged (no history)", len(fresh), len(merged))
        return merged, emb_map

    # Embed historical titles (skip those already in map)
    hist_titles_to_embed = [
        h["title"] for h in historical
        if h["title"].lower() not in emb_map
    ]
    if hist_titles_to_embed:
        hist_embs = await embed_texts(hist_titles_to_embed)
        for title, emb in zip(hist_titles_to_embed, hist_embs):
            emb_map[title.lower()] = emb

    # Build fresh embedding matrix
    fresh_vecs = []
    for s in fresh:
        emb = emb_map.get(s["title"].lower())
        fresh_vecs.append(np.array(emb, dtype=np.float32) if emb is not None else np.zeros(1536, dtype=np.float32))
    fresh_matrix = np.array(fresh_vecs)
    fresh_norms = np.linalg.norm(fresh_matrix, axis=1, keepdims=True)
    fresh_norms = np.where(fresh_norms == 0, 1, fresh_norms)
    fresh_normed = fresh_matrix / fresh_norms

    # Build occurrence map from historical
    hist_occurrence: dict[int, int] = {}
    for i, h in enumerate(historical):
        hist_occurrence[i] = h.get("occurrence_count", 1)

    # Match each historical signal to fresh signals by embedding similarity
    matched_hist: set[int] = set()
    boosted = 0
    for hi, h in enumerate(historical):
        h_emb = emb_map.get(h["title"].lower())
        if h_emb is None:
            continue
        h_vec = np.array(h_emb, dtype=np.float32)
        h_norm = np.linalg.norm(h_vec)
        if h_norm == 0:
            continue
        h_normed = h_vec / h_norm

        sims = fresh_normed @ h_normed
        best_idx = int(np.argmax(sims))
        best_sim = float(sims[best_idx])

        if best_sim >= MATCH_SIMILARITY:
            sig = fresh[best_idx]
            occ = hist_occurrence.get(hi, 1)
            boost = min(occ * boost_per_occurrence, max_boost)
            sig["viral_score"] = sig.get("viral_score", 0) + boost
            sig["engagement"] = max(
                sig.get("engagement", 0),
                h.get("engagement", 0),
            )
            matched_hist.add(hi)
            boosted += 1

    # Recycle unmatched historical signals with decay (if not too similar to any fresh)
    recycled = 0
    recycled_embs: list[np.ndarray] = []
    for hi, h in enumerate(historical):
        if hi in matched_hist:
            continue
        h_emb = emb_map.get(h["title"].lower())
        if h_emb is None:
            continue
        h_vec = np.array(h_emb, dtype=np.float32)
        h_norm = np.linalg.norm(h_vec)
        if h_norm == 0:
            continue
        h_normed = h_vec / h_norm

        # Skip if too similar to any fresh signal
        sims = fresh_normed @ h_normed
        if float(np.max(sims)) >= RECYCLE_SIMILARITY:
            continue

        # Skip if too similar to already-recycled signals
        if recycled_embs:
            rec_matrix = np.array(recycled_embs)
            rec_sims = rec_matrix @ h_normed
            if float(np.max(rec_sims)) >= RECYCLE_SIMILARITY:
                continue

        h["viral_score"] = h.get("viral_score", 0) * 0.6
        h["engagement"] = int(h.get("engagement", 0) * 0.5)
        h.pop("occurrence_count", None)
        h.pop("subreddit", None)
        fresh.append(h)
        recycled_embs.append(h_normed)
        recycled += 1

    merged = sorted(fresh, key=lambda s: s.get("viral_score", 0), reverse=True)
    log.info(
        "Signal memory: {} fresh + {} historical -> {} merged ({} boosted, {} recycled)",
        len(fresh) - recycled, len(historical), len(merged), boosted, recycled,
    )
    return merged, emb_map
