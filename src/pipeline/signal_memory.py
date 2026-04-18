"""Merge fresh signals with historical signals from past pipeline runs.

Recurring signals (appeared in multiple batches) get boosted scores,
making them more likely to surface as fused topics.
"""
from __future__ import annotations

from loguru import logger as log


def merge_with_history(
    fresh: list[dict],
    historical: list[dict],
    boost_per_occurrence: float = 1.5,
    max_boost: float = 4.0,
) -> list[dict]:
    """Merge fresh signals with historical ones.

    - Recurring signals get their viral_score boosted by occurrence count.
    - Historical signals not in fresh batch are re-added with a decay factor.
    - Deduplicates by lowercase title.
    """
    fresh_keys: dict[str, dict] = {}
    for s in fresh:
        key = s["title"].lower().strip()[:80]
        fresh_keys[key] = s

    hist_by_key: dict[str, dict] = {}
    occurrence_counts: dict[str, int] = {}
    for s in historical:
        key = s["title"].lower().strip()[:80]
        occ = s.get("occurrence_count", 1)
        if key not in hist_by_key or occ > occurrence_counts.get(key, 0):
            hist_by_key[key] = s
            occurrence_counts[key] = occ

    boosted = 0
    for key, sig in fresh_keys.items():
        if key in occurrence_counts:
            occ = occurrence_counts[key]
            boost = min(occ * boost_per_occurrence, max_boost)
            sig["viral_score"] = sig.get("viral_score", 0) + boost
            sig["engagement"] = max(
                sig.get("engagement", 0),
                hist_by_key[key].get("engagement", 0),
            )
            boosted += 1

    recycled = 0
    for key, sig in hist_by_key.items():
        if key not in fresh_keys:
            sig["viral_score"] = sig.get("viral_score", 0) * 0.6
            sig["engagement"] = int(sig.get("engagement", 0) * 0.5)
            sig.pop("occurrence_count", None)
            sig.pop("subreddit", None)
            fresh_keys[key] = sig
            recycled += 1

    merged = sorted(fresh_keys.values(), key=lambda s: s.get("viral_score", 0), reverse=True)
    log.info(
        "Signal memory: {} fresh + {} historical -> {} merged ({} boosted, {} recycled)",
        len(fresh), len(historical), len(merged), boosted, recycled,
    )
    return merged
