from __future__ import annotations


from src.config import get_blacklist, settings
from src.storage.models import Priority, ScoredTopic
from loguru import logger as log



def _is_blacklisted(title: str, blacklist: list[str]) -> bool:
    lower = title.lower()
    return any(kw in lower for kw in blacklist)


def filter_and_prioritize(
    topics: list[ScoredTopic],
    existing_titles: set[str] | None = None,
) -> list[ScoredTopic]:
    """Filter WRITE topics, remove duplicates/blacklisted, assign priority."""
    blacklist = get_blacklist()
    existing = existing_titles or set()

    writable = []
    for t in topics:
        if t.decision != "WRITE" or t.is_duplicate:
            continue
        if _is_blacklisted(t.title, blacklist):
            log.info("Blacklisted: '%s'", t.title)
            continue
        if t.title.lower() in existing:
            log.info("Already exists in DB: '%s'", t.title)
            continue
        writable.append(t)

    for t in writable:
        if t.viral_score >= settings.viral_threshold and t.score >= 8:
            t.priority = Priority.high
        elif t.score >= 7:
            t.priority = Priority.medium
        else:
            t.priority = Priority.low

    writable.sort(key=lambda t: (
        0 if t.priority == Priority.high else 1 if t.priority == Priority.medium else 2,
        -t.score,
    ))

    log.info(
        "Filtered: %d writable topics (high=%d, medium=%d, low=%d) from %d total",
        len(writable),
        sum(1 for t in writable if t.priority == Priority.high),
        sum(1 for t in writable if t.priority == Priority.medium),
        sum(1 for t in writable if t.priority == Priority.low),
        len(topics),
    )
    return writable
