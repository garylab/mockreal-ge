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


async def fuse(signals: list[dict], recent_titles: set[str] | None = None) -> list[dict]:
    """Cross-link signals and generate multi-signal hybrid topics via GPT-4o."""
    classified = _classify(signals)

    url_index: dict[str, list[str]] = {}
    query_index: dict[str, list[str]] = {}
    for bucket_name, bucket_signals in classified.items():
        for s in bucket_signals:
            title_key = s["title"].lower().strip()
            if s.get("url"):
                url_index.setdefault(title_key, []).append(s["url"])
            query_index.setdefault(title_key, []).append(s["title"])

    pain_block = "\n".join(f"- {s['title']} (eng:{s['engagement']})" for s in classified["pain"][:20])
    intent_block = "\n".join(f"- {s['title']} (eng:{s['engagement']})" for s in classified["intent"][:20])
    trend_block = "\n".join(f"- {s['title']} (eng:{s['engagement']})" for s in classified["trend"][:15])
    support_block = "\n".join(f"- {s['title']} (eng:{s['engagement']})" for s in classified["support"][:15])

    avoid_block = ""
    if recent_titles:
        titles_list = "\n".join(f"- {t}" for t in sorted(recent_titles)[:50])
        avoid_block = (
            "RECENTLY PUBLISHED (do NOT generate topics similar to these):\n"
            + titles_list + "\n\n"
        )

    prompt = (
        "You are a topic strategist for 'mockreal', an AI mock interview platform.\n\n"
        "Below are signals from multiple sources classified by type.\n\n"
        "PAIN SIGNALS (Reddit):\n" + (pain_block or "(none)") + "\n\n"
        "INTENT SIGNALS (Autocomplete + PAA):\n" + (intent_block or "(none)") + "\n\n"
        "TREND SIGNALS (Google Trends):\n" + (trend_block or "(none)") + "\n\n"
        "SUPPORT SIGNALS (News, Search, YouTube):\n" + (support_block or "(none)") + "\n\n"
        + avoid_block
        + "TASK:\n"
        "1. Cross-link signals: find overlaps between pain↔intent, intent↔trend, pain↔trend.\n"
        "2. Generate 12-20 HYBRID topic ideas, each based on at least 2 signal types.\n"
        "3. For each topic generate 4 angles: emotional, seo, tactical, product.\n"
        "4. Topics MUST be distinct from the recently published list above.\n\n"
        "TITLE RULES (CRITICAL — titles must pass as human-written):\n"
        "- Sound like a real blog post title, NOT a BuzzFeed headline or AI listicle.\n"
        "- AVOID these AI patterns: numbered lists ('7 Ways...', '10 Tips...'), "
        "parenthetical qualifiers ('(Real Examples Inside)', '(Not Just X)'), "
        "'Actually', 'That Actually Work', 'You Need to Know', 'Nobody Talks About', "
        "'The Truth About', 'Here\'s Why', 'Game-Changer', 'Ultimate Guide'.\n"
        "- Good title styles: direct statement ('Mock interviews won\'t fix bad answers'), "
        "simple question ('Why do most interview prep tools miss the point?'), "
        "practical framing ('What I learned from 50 mock interviews'), "
        "contrarian take ('Stop memorizing interview answers').\n"
        "- Keep titles 6-12 words. No clickbait, no hype, no exclamation marks.\n\n"
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
        matched_urls: list[str] = []
        matched_queries: list[str] = []
        title_words = set(t.get("title", "").lower().split())
        for sig_title, urls in url_index.items():
            if len(title_words & set(sig_title.split())) >= 2:
                matched_urls.extend(urls)
        for sig_title, queries in query_index.items():
            if len(title_words & set(sig_title.split())) >= 2:
                matched_queries.extend(queries)

        results.append({
            "title": t.get("title", ""),
            "source": "fused",
            "suggested_angle": t.get("suggested_angle", ""),
            "signal_types": t.get("signals_used", []),
            "reasoning": t.get("reasoning", ""),
            "angles": t.get("angles", {}),
            "viral_score": 6,
            "seo_potential": 7,
            "source_urls": list(dict.fromkeys(matched_urls))[:10],
            "source_queries": list(dict.fromkeys(matched_queries))[:10],
        })
    log.info("Fused {} hybrid topics from {} signals", len(results), len(signals))
    return results
