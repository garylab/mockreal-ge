from __future__ import annotations

import json

from src.config import CLUSTERS
from src.storage.models import ScoredTopic
from src.utils.ai_client import chat_gpt
from loguru import logger as log



async def score(
    topics: list[dict],
    cluster_feedback: list[dict],
) -> list[ScoredTopic]:
    """Send all topics to GPT-4o for scoring, return ScoredTopic list."""
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
        f"Assign a CLUSTER from: {', '.join(CLUSTERS)}\n"
        "Flag near-duplicates (is_duplicate: true).\n\n"
        'Return JSON: {"scored_topics":[{"index":1,"original_title":"...","score":8,'
        '"reasoning":"...","decision":"WRITE","suggested_angle":"...",'
        '"cluster":"interview_prep","is_duplicate":false}]}\n'
        "WRITE if score>=7, IGNORE if <7."
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
    results: list[ScoredTopic] = []
    for st in scored_list:
        idx = st.get("index", 1) - 1
        orig = topics[idx] if 0 <= idx < len(topics) else {}
        results.append(ScoredTopic(
            title=st.get("original_title", orig.get("title", "")),
            source=orig.get("source", "fused"),
            score=st.get("score", 0),
            reasoning=st.get("reasoning", ""),
            decision=st.get("decision", "IGNORE"),
            suggested_angle=st.get("suggested_angle", orig.get("suggested_angle", "")),
            cluster=st.get("cluster", "other"),
            is_duplicate=st.get("is_duplicate", False),
            viral_score=orig.get("viral_score", 0),
            seo_potential=orig.get("seo_potential", 0),
            signal_types=orig.get("signal_types", []),
            angles=orig.get("angles", {}),
            derivation_strategy=orig.get("derivation_strategy"),
            parent_title=orig.get("parent_title"),
        ))

    log.info("Scored %d topics: %d WRITE, %d IGNORE",
             len(results),
             sum(1 for t in results if t.decision == "WRITE"),
             sum(1 for t in results if t.decision == "IGNORE"))
    return results
