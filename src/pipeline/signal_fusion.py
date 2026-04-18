from __future__ import annotations

import json

from src.utils.ai_client import chat_gpt
from loguru import logger as log



def _classify(signals: list[dict]) -> dict[str, list[dict]]:
    buckets: dict[str, list[dict]] = {"pain": [], "intent": [], "trend": [], "support": []}
    for s in signals:
        src = s["source"]
        if src == "reddit":
            buckets["pain"].append(s)
        elif src in ("google_autocomplete", "people_also_ask"):
            buckets["intent"].append(s)
        elif src == "google_trends":
            buckets["trend"].append(s)
        else:
            buckets["support"].append(s)
    return buckets


async def fuse(signals: list[dict]) -> list[dict]:
    """Cross-link signals and generate multi-signal hybrid topics via GPT-4o."""
    classified = _classify(signals)

    pain_block = "\n".join(f"- {s['title']} (eng:{s['engagement']})" for s in classified["pain"][:20])
    intent_block = "\n".join(f"- {s['title']} (eng:{s['engagement']})" for s in classified["intent"][:20])
    trend_block = "\n".join(f"- {s['title']} (eng:{s['engagement']})" for s in classified["trend"][:15])
    support_block = "\n".join(f"- {s['title']} (eng:{s['engagement']})" for s in classified["support"][:15])

    prompt = (
        "You are a topic strategist for 'mockreal', an AI mock interview platform.\n\n"
        "Below are signals from multiple sources classified by type.\n\n"
        "PAIN SIGNALS (Reddit):\n" + (pain_block or "(none)") + "\n\n"
        "INTENT SIGNALS (Autocomplete + PAA):\n" + (intent_block or "(none)") + "\n\n"
        "TREND SIGNALS (Google Trends):\n" + (trend_block or "(none)") + "\n\n"
        "SUPPORT SIGNALS (News, Search, YouTube):\n" + (support_block or "(none)") + "\n\n"
        "TASK:\n"
        "1. Cross-link signals: find overlaps between pain↔intent, intent↔trend, pain↔trend.\n"
        "2. Generate 8-15 HYBRID topic ideas, each based on at least 2 signal types.\n"
        "3. For each topic generate 4 angles: emotional, seo, tactical, product.\n\n"
        'Return JSON: {"fused_topics": [{"title":"...","signals_used":["pain","intent"],'
        '"reasoning":"...","suggested_angle":"...","angles":{"emotional":"...","seo":"...",'
        '"tactical":"...","product":"..."}}]}'
    )

    raw = await chat_gpt(
        messages=[{"role": "user", "content": prompt}],
        temperature=0.7,
        response_format={"type": "json_object"},
        max_tokens=4096,
    )

    try:
        data = json.loads(raw)
    except json.JSONDecodeError:
        log.error("Failed to parse fusion response")
        return []

    topics = data.get("fused_topics", [])
    results = []
    for t in topics:
        results.append({
            "title": t.get("title", ""),
            "source": "fused",
            "suggested_angle": t.get("suggested_angle", ""),
            "signal_types": t.get("signals_used", []),
            "reasoning": t.get("reasoning", ""),
            "angles": t.get("angles", {}),
            "viral_score": 6,
            "seo_potential": 7,
        })
    log.info("Fused {} hybrid topics from {} signals", len(results), len(signals))
    return results
