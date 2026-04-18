from __future__ import annotations

import numpy as np

from src.storage.models import RawSignal
from src.utils.ai_client import embed_texts
from loguru import logger as log

DEDUP_SIMILARITY = 0.88


async def normalize_all(signal_batches: list[list[RawSignal]]) -> tuple[list[RawSignal], dict[str, list[float]]]:
    """Flatten, deduplicate by embedding similarity, sort by engagement.

    Returns (unique_signals, embedding_map) where embedding_map maps
    lowercase titles to their embedding vectors for downstream reuse.
    """
    all_signals: list[RawSignal] = []
    for batch in signal_batches:
        if isinstance(batch, list):
            all_signals.extend(batch)

    if not all_signals:
        return [], {}

    # Exact-match pre-filter to reduce embedding API calls
    seen_exact: set[str] = set()
    candidates: list[RawSignal] = []
    for sig in all_signals:
        key = sig.title.lower().strip()
        if key and key not in seen_exact:
            seen_exact.add(key)
            candidates.append(sig)

    log.info("Pre-filter: {} raw -> {} exact-unique, embedding...", len(all_signals), len(candidates))

    titles = [s.title for s in candidates]
    embeddings = await embed_texts(titles)

    emb_map: dict[str, list[float]] = {}
    for title, emb in zip(titles, embeddings):
        emb_map[title.lower()] = emb

    # Cosine-similarity dedup: keep highest-engagement signal per cluster
    emb_matrix = np.array(embeddings, dtype=np.float32)
    norms = np.linalg.norm(emb_matrix, axis=1, keepdims=True)
    norms = np.where(norms == 0, 1, norms)
    emb_normed = emb_matrix / norms

    unique: list[RawSignal] = []
    kept_indices: list[int] = []
    for i, sig in enumerate(candidates):
        is_dup = False
        if kept_indices:
            sims = emb_normed[i] @ emb_normed[kept_indices].T
            if np.max(sims) >= DEDUP_SIMILARITY:
                is_dup = True
        if not is_dup:
            unique.append(sig)
            kept_indices.append(i)

    unique.sort(key=lambda s: s.engagement, reverse=True)
    log.info("Normalized {} raw signals -> {} unique (semantic dedup)", len(all_signals), len(unique))
    return unique, emb_map
