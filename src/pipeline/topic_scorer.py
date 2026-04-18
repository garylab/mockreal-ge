from __future__ import annotations

import json

import numpy as np

from src.config import CLUSTERS, settings
from src.storage.models import ScoredTopic
from src.utils.ai_client import chat_gpt, embed_texts
from loguru import logger as log

SCORER_DEDUP_SIMILARITY = 0.87


def _mark_embedding_duplicates(
    results: list[ScoredTopic],
    embeddings: dict[str, list[float]],
) -> int:
    """Mark lower-scored topics as duplicates when cosine sim >= threshold.

    Within each group of near-duplicates, only the highest-scored topic
    survives; the rest get is_duplicate=True and decision=IGNORE.
    Returns the number of duplicates marked.
    """
    titles = [t.title.lower() for t in results]
    vecs = [embeddings.get(t) for t in titles]

    indexed: list[tuple[int, np.ndarray]] = []
    for i, v in enumerate(vecs):
        if v is not None:
            indexed.append((i, np.array(v, dtype=np.float32)))

    if len(indexed) < 2:
        return 0

    indices = [x[0] for x in indexed]
    matrix = np.array([x[1] for x in indexed])
    norms = np.linalg.norm(matrix, axis=1, keepdims=True)
    norms = np.where(norms == 0, 1, norms)
    normed = matrix / norms
    sim_matrix = normed @ normed.T

    marked = 0
    already_dup: set[int] = set()
    for a in range(len(indexed)):
        if indices[a] in already_dup:
            continue
        for b in range(a + 1, len(indexed)):
            if indices[b] in already_dup:
                continue
            if sim_matrix[a, b] >= SCORER_DEDUP_SIMILARITY:
                topic_a = results[indices[a]]
                topic_b = results[indices[b]]
                if topic_a.score >= topic_b.score:
                    loser = indices[b]
                else:
                    loser = indices[a]
                results[loser].is_duplicate = True
                results[loser].decision = "IGNORE"
                already_dup.add(loser)
                log.info("Scorer dedup: '{}' marked as duplicate of '{}' (sim={:.3f})",
                         results[loser].title,
                         results[indices[a] if loser == indices[b] else indices[b]].title,
                         float(sim_matrix[a, b]))
                marked += 1
    return marked


async def score(
    topics: list[dict],
    cluster_feedback: list[dict],
    topic_embeddings: dict[str, list[float]] | None = None,
) -> list[ScoredTopic]:
    """Send all topics to GPT-4o for scoring, return ScoredTopic list.

    If topic_embeddings is provided, uses cosine similarity to detect
    duplicates instead of relying on GPT's is_duplicate flag.
    """
    if not topics:
        return []

    history_block = ""
    if cluster_feedback:
        lines = [
            f"{f['cluster']}: avg_ctr={float(f.get('avg_ctr',0)):.1f}% "
            f"avg_conv={float(f.get('avg_conversion',0)):.1f}% posts={f.get('total_posts',0)}"
            for f in cluster_feedback
        ]
        history_block = "\n\nHISTORICAL PERFORMANCE:\n" + "\n".join(lines)

    topic_lines = []
    for i, t in enumerate(topics):
        label = f"[DERIVED: \"{t.get('parent_title','')[:50]}\"]" if t.get("source") == "content_derived" else ""
        topic_lines.append(
            f"{i+1}. \"{t['title']}\" [signals: {'+'.join(t.get('signal_types',[]))}] "
            f"(viral:{t.get('viral_score',0)}, seo:{t.get('seo_potential',0)}) {label}"
        )

    system_msg = (
        "You are a content strategist for 'mockreal', an AI mock interview platform.\n\n"
        "Score each topic 0-10 based on:\n"
        "- Relevance to AI interviews/jobs/career/hiring (40%)\n"
        "- Viral potential (20%)\n- SEO potential (20%)\n- Freshness (20%)\n\n"
        f"Assign a CLUSTER from: {', '.join(CLUSTERS)}\n\n"
        'Return JSON: {"scored_topics":[{"index":1,"original_title":"...","score":8,'
        '"reasoning":"...","decision":"WRITE","suggested_angle":"...",'
        '"cluster":"interview_prep"}]}\n'
        f"WRITE if score>={settings.score_threshold}, IGNORE if below."
    )

    user_msg = (
        f"Score these {len(topics)} topics:{history_block}\n\nTOPICS:\n"
        + "\n".join(topic_lines)
    )

    raw = await chat_gpt(
        messages=[
            {"role": "system", "content": system_msg},
            {"role": "user", "content": user_msg},
        ],
        temperature=0.3,
        response_format={"type": "json_object"},
    )

    try:
        data = json.loads(raw)
    except json.JSONDecodeError:
        log.error("Failed to parse scoring response")
        return []

    scored_list = data.get("scored_topics", [])
    threshold = settings.score_threshold
    results: list[ScoredTopic] = []
    for st in scored_list:
        idx = st.get("index", 1) - 1
        orig = topics[idx] if 0 <= idx < len(topics) else {}
        topic_score = st.get("score") or 0
        decision = "WRITE" if topic_score >= threshold else "IGNORE"
        results.append(ScoredTopic(
            title=st.get("original_title") or orig.get("title", ""),
            source=orig.get("source", "fused"),
            score=topic_score,
            reasoning=st.get("reasoning") or "",
            decision=decision,
            suggested_angle=st.get("suggested_angle") or orig.get("suggested_angle") or "",
            cluster=st.get("cluster") or "other",
            is_duplicate=False,
            viral_score=orig.get("viral_score", 0),
            seo_potential=orig.get("seo_potential", 0),
            signal_types=orig.get("signal_types", []),
            angles=orig.get("angles", {}),
            source_urls=orig.get("source_urls", []),
            source_queries=orig.get("source_queries", []),
            derivation_strategy=orig.get("derivation_strategy"),
            parent_title=orig.get("parent_title"),
        ))

    # Embed-based duplicate detection (replaces GPT's unreliable is_duplicate flag)
    emb_map = topic_embeddings or {}
    titles_to_embed = [t.title for t in results if t.title.lower() not in emb_map]
    if titles_to_embed:
        new_embs = await embed_texts(titles_to_embed)
        for title, emb in zip(titles_to_embed, new_embs):
            emb_map[title.lower()] = emb
    dup_count = _mark_embedding_duplicates(results, emb_map)

    write_count = sum(1 for t in results if t.decision == "WRITE")
    ignore_count = len(results) - write_count
    log.info("Scored {} topics (threshold={}): {} WRITE, {} IGNORE ({} embedding-dups)",
             len(results), threshold, write_count, ignore_count, dup_count)
    return results
