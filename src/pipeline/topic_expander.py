from __future__ import annotations

import json

from src.utils.ai_client import chat_gpt
from loguru import logger as log



async def expand(top_performers: list[dict]) -> list[dict]:
    """Generate derivative topics from proven high-performing content."""
    if not top_performers:
        log.info("No top performers to expand")
        return []

    perf_lines = []
    for i, p in enumerate(top_performers):
        perf_lines.append(
            f"{i+1}. \"{p.get('title','')}\"\n"
            f"   Cluster: {p.get('cluster','other')}\n"
            f"   CTR: {p.get('avg_ctr',0)}% | Conv: {p.get('avg_conv',0)}%\n"
            f"   Clicks: {p.get('total_clicks',0)} | Signups: {p.get('total_signups',0)}"
        )

    system_msg = (
        "You are a content strategist for 'mockreal', an AI mock interview platform.\n\n"
        "Given TOP PERFORMING published articles, generate DERIVATIVE topic ideas.\n\n"
        "Strategies:\n"
        "- DEEPER DIVE: Narrow subtopic focus\n"
        "- ADJACENT ANGLE: Related different perspective\n"
        "- COUNTER TAKE: Contrarian view\n"
        "- UPDATED VERSION: Time-sensitive refresh\n"
        "- LISTICLE SPIN: Format transformation\n\n"
        "Generate 2-3 derivatives per top performer.\n\n"
        'Return JSON: {"derived_topics":[{"title":"...","strategy":"...","parent_title":"...",'
        '"cluster":"...","suggested_angle":"...","reasoning":"..."}]}'
    )

    raw = await chat_gpt(
        messages=[
            {"role": "system", "content": system_msg},
            {"role": "user", "content": f"Derive from these {len(top_performers)} top performers:\n\n" + "\n\n".join(perf_lines)},
        ],
        temperature=0.7,
        response_format={"type": "json_object"},
    )

    try:
        data = json.loads(raw)
    except json.JSONDecodeError:
        log.error("Failed to parse expansion response")
        return []

    derived = data.get("derived_topics", [])
    results = []
    for d in derived:
        results.append({
            "title": d.get("title", ""),
            "source": "content_derived",
            "derivation_strategy": d.get("strategy", ""),
            "parent_title": d.get("parent_title", ""),
            "cluster": d.get("cluster", "other"),
            "suggested_angle": d.get("suggested_angle", ""),
            "reasoning": d.get("reasoning", ""),
            "viral_score": 6,
            "seo_potential": 7,
            "signal_types": ["content_derived", "proven_performer"],
            "angles": {
                "emotional": d.get("suggested_angle", d.get("title", "")),
                "seo": d.get("title", ""),
                "tactical": f"Step-by-step: {d.get('title','')}",
                "product": f"Practice with mockreal: {d.get('title','')[:60]}",
            },
        })

    log.info("Expanded %d derivative topics from %d performers", len(results), len(top_performers))
    return results
