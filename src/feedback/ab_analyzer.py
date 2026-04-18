from __future__ import annotations


from src.storage import database as db
from loguru import logger as log



async def analyze_ab_results() -> dict:
    """Analyze which CTA variant (a=emotional, b=logical) performs better.
    Returns the winning variant and stats."""
    rows = await db.fetch_ab_results()
    if not rows:
        log.info("No A/B data yet")
        return {"winner": None, "confidence": "low", "stats": {}}

    stats = {}
    for r in rows:
        variant = r["cta_variant"]
        stats[variant] = {
            "total_publishes": int(r["total_publishes"]),
            "avg_ctr": round(float(r["avg_ctr"]), 2),
            "avg_conv": round(float(r["avg_conv"]), 2),
            "total_clicks": int(r["total_clicks"]),
            "total_signups": int(r["total_signups"]),
        }

    a = stats.get("A", {})
    b = stats.get("B", {})

    a_score = a.get("avg_conv", 0) * 0.6 + a.get("avg_ctr", 0) * 0.4
    b_score = b.get("avg_conv", 0) * 0.6 + b.get("avg_ctr", 0) * 0.4

    total_samples = sum(s.get("total_publishes", 0) for s in stats.values())
    confidence = "high" if total_samples >= 50 else "medium" if total_samples >= 20 else "low"

    if a_score > b_score * 1.1:
        winner = "A"
    elif b_score > a_score * 1.1:
        winner = "B"
    else:
        winner = "tie"

    log.info(
        "A/B results: variant_a={:.2f}, variant_b={:.2f}, winner={} (confidence={}, n={})",
        a_score, b_score, winner, confidence, total_samples,
    )
    return {"winner": winner, "confidence": confidence, "stats": stats}


async def get_preferred_variant() -> str:
    """Return the winning CTA variant for publishing, or random if tie/low confidence."""
    import random
    result = await analyze_ab_results()
    if result["confidence"] in ("high", "medium") and result["winner"] in ("A", "B"):
        return result["winner"]
    return random.choice(["A", "B"])
