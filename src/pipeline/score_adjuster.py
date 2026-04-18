from __future__ import annotations


from src.storage.models import ScoredTopic
from loguru import logger as log



def adjust(
    topics: list[ScoredTopic],
    cluster_perf: dict[str, dict],
) -> list[ScoredTopic]:
    """Boost or penalize scores based on historical cluster performance."""
    for t in topics:
        perf = cluster_perf.get(t.cluster)
        if not perf:
            continue
        adj = 0
        avg_conv = perf.get("avg_conversion", 0)
        if avg_conv > 3:
            adj = 2
        elif avg_conv > 1.5:
            adj = 1
        elif 0 < avg_conv < 0.5:
            adj = -2
        elif 0 < avg_conv < 1:
            adj = -1

        t.original_score = t.score
        t.score_adjustment = adj
        t.score = max(0, min(10, t.score + adj))
        t.decision = "WRITE" if t.score >= 7 else "IGNORE"

    adjusted = sum(1 for t in topics if t.score_adjustment != 0)
    log.info("Adjusted {}/{} topics based on cluster performance", adjusted, len(topics))
    return topics
