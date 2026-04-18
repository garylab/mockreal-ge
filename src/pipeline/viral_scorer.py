from __future__ import annotations


from src.storage.models import RawSignal
from loguru import logger as log


THRESHOLDS = {
    "reddit":              {"low": 50, "mid": 200, "high": 500},
    "google_trends":       {"low": 20, "mid": 50,  "high": 80},
    "google_news":         {"low": 3,  "mid": 5,   "high": 10},
    "google_search":       {"low": 3,  "mid": 6,   "high": 9},
    "google_autocomplete": {"low": 3,  "mid": 5,   "high": 7},
    "youtube":             {"low": 5,  "mid": 20,  "high": 50},
    "people_also_ask":     {"low": 3,  "mid": 5,   "high": 7},
}


def _score_signal(sig: RawSignal) -> float:
    th = THRESHOLDS.get(sig.source, {"low": 5, "mid": 15, "high": 30})
    eng = sig.engagement
    if eng >= th["high"]:
        return 9
    if eng >= th["mid"]:
        return 7
    if eng >= th["low"]:
        return 5
    return 3


def score(signals: list[RawSignal]) -> list[dict]:
    """Attach a viral_score and seo_potential to each signal."""
    results = []
    for sig in signals:
        vs = _score_signal(sig)
        seo = 7 if sig.source in ("google_search", "google_autocomplete", "people_also_ask") else 5
        results.append({
            "title": sig.title,
            "source": sig.source,
            "url": sig.url,
            "engagement": sig.engagement,
            "snippet": sig.snippet,
            "viral_score": vs,
            "seo_potential": seo,
            "extra": sig.extra,
        })
    log.info("Scored {} signals for virality", len(results))
    return results
