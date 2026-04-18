from __future__ import annotations


from src.storage.models import RawSignal
from loguru import logger as log



def normalize_all(signal_batches: list[list[RawSignal]]) -> list[RawSignal]:
    """Flatten, deduplicate by title similarity, and sort by engagement."""
    all_signals: list[RawSignal] = []
    for batch in signal_batches:
        if isinstance(batch, list):
            all_signals.extend(batch)

    seen_titles: set[str] = set()
    unique: list[RawSignal] = []
    for sig in all_signals:
        key = sig.title.lower().strip()[:60]
        if key and key not in seen_titles:
            seen_titles.add(key)
            unique.append(sig)

    unique.sort(key=lambda s: s.engagement, reverse=True)
    log.info("Normalized %d raw signals -> %d unique", len(all_signals), len(unique))
    return unique
