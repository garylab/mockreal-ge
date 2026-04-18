from __future__ import annotations

import json
import re
from urllib.parse import quote_plus

import httpx
from loguru import logger as log
from tenacity import retry, stop_after_attempt, wait_exponential

from src.config import settings
from src.storage.models import ContentPackage
from src.storage.r2_client import upload_image
from src.utils.charts import comparison_bar, donut, stat_highlight, trend_line
from src.utils.screenshot import (
    capture_google_trends,
    capture_reddit_post,
    capture_url,
    screenshot_and_upload,
)

_MARKER_RE = re.compile(
    r"<!--\s*IMG:(evidence|explanatory|rhythm|chart):(.+?)\s*-->", re.IGNORECASE
)


@retry(stop=stop_after_attempt(2), wait=wait_exponential(min=1, max=5))
async def _search_pexels(query: str) -> dict | None:
    async with httpx.AsyncClient(timeout=15) as client:
        resp = await client.get(
            "https://api.pexels.com/v1/search",
            params={"query": query, "per_page": 3, "orientation": "landscape"},
            headers={"Authorization": settings.pexels_api_key},
        )
        resp.raise_for_status()
        data = resp.json()
    photos = data.get("photos", [])
    return photos[0] if photos else None


async def _download(url: str) -> bytes:
    async with httpx.AsyncClient(timeout=30) as client:
        resp = await client.get(url)
        resp.raise_for_status()
        return resp.content


async def _resolve_evidence(
    desc: str, source_urls: list[str], source_queries: list[str],
) -> str | None:
    """Try to capture a real screenshot for an evidence marker."""
    desc_lower = desc.lower()

    if "google trends" in desc_lower or "search spike" in desc_lower or "trend" in desc_lower:
        query = _extract_query_from_desc(desc, source_queries)
        if query:
            url = await screenshot_and_upload(
                capture_google_trends, query, filename_prefix="trends",
            )
            if url:
                return url

    if "reddit" in desc_lower:
        for u in source_urls:
            if "reddit.com" in u:
                url = await screenshot_and_upload(
                    capture_reddit_post, u, filename_prefix="reddit",
                )
                if url:
                    return url

    for u in source_urls[:3]:
        if any(kw in u for kw in ("trends", "reddit", "twitter", "x.com", "news")):
            url = await screenshot_and_upload(
                capture_url, u, filename_prefix="evidence",
            )
            if url:
                return url

    return None


async def _resolve_pexels(desc: str) -> tuple[str, str, str, str] | None:
    """Search Pexels for a contextual image. Returns (url, alt, credit, credit_url)."""
    if not settings.pexels_api_key:
        return None

    photo = await _search_pexels(desc)
    if not photo:
        return None

    img_url = photo.get("src", {}).get("large2x") or photo.get("src", {}).get("large", "")
    if not img_url:
        return None

    img_bytes = await _download(img_url)
    filename = f"pexels-{photo['id']}.jpg"
    public_url = upload_image(img_bytes, filename)

    alt = (photo.get("alt") or desc).replace('"', "&quot;")
    credit = photo.get("photographer", "Pexels")
    credit_url = photo.get("photographer_url") or photo.get("url", "https://www.pexels.com")

    return public_url, alt, credit, credit_url


def _extract_query_from_desc(desc: str, source_queries: list[str]) -> str:
    """Extract a search query from the image description, matching against source queries."""
    desc_words = set(desc.lower().split())
    best_match = ""
    best_overlap = 0
    for q in source_queries:
        q_words = set(q.lower().split())
        overlap = len(desc_words & q_words)
        if overlap > best_overlap:
            best_overlap = overlap
            best_match = q
    if best_match:
        return best_match

    cleaned = re.sub(r"(google trends|chart|showing|screenshot|data|for)\s*", "", desc, flags=re.I)
    cleaned = re.sub(r"['\"]", "", cleaned).strip()
    return cleaned[:60] if cleaned else ""


async def _resolve_chart(desc: str) -> str | None:
    """Generate a data chart from a description using AI to extract chart parameters."""
    from src.utils.ai_client import chat_gpt

    prompt = (
        "Extract chart data from this image description. Return JSON only.\n\n"
        f"Description: {desc}\n\n"
        "Determine the best chart type and provide data:\n"
        '{"chart_type": "trend_line|bar|donut|stat_cards",\n'
        ' "title": "chart title",\n'
        ' "labels": ["label1", "label2", ...],\n'
        ' "values": [10, 20, ...],\n'
        ' "ylabel": "optional y-axis label",\n'
        ' "stats": [{"label":"...", "value":"85%", "subtitle":"..."}]}\n\n'
        "For stat_cards, use the stats array. For others, use labels+values.\n"
        "Invent plausible, realistic data that matches the description.\n"
        "Return ONLY valid JSON, no markdown."
    )

    try:
        raw = await chat_gpt(
            messages=[{"role": "user", "content": prompt}],
            temperature=0.3,
            response_format={"type": "json_object"},
            max_tokens=512,
        )
        data = json.loads(raw)
    except Exception as exc:
        log.debug("Chart data extraction failed: {}", exc)
        return None

    chart_type = data.get("chart_type", "bar")
    title = data.get("title", "")
    labels = data.get("labels", [])
    values = data.get("values", [])
    ylabel = data.get("ylabel", "")

    if chart_type == "trend_line" and labels and values:
        return trend_line(labels, values, title=title, ylabel=ylabel)
    elif chart_type == "bar" and labels and values:
        horiz = len(labels) > 5
        return comparison_bar(labels, values, title=title, ylabel=ylabel, horizontal=horiz)
    elif chart_type == "donut" and labels and values:
        return donut(labels, values, title=title)
    elif chart_type == "stat_cards" and data.get("stats"):
        return stat_highlight(data["stats"], title=title)
    elif labels and values:
        return comparison_bar(labels, values, title=title, ylabel=ylabel)

    return None


def _build_figure(url: str, alt: str, credit: str = "", credit_url: str = "") -> str:
    caption = ""
    if credit:
        caption = (
            f'<figcaption>Photo by <a href="{credit_url}">{credit}</a>'
            f" on Pexels</figcaption>"
        )
    return (
        f'<figure><img src="{url}" alt="{alt}" loading="lazy" width="800" />'
        f"{caption}</figure>"
    )


async def enrich(pkg: ContentPackage) -> ContentPackage:
    """Process <!-- IMG:type:desc --> markers in article HTML, replacing with real images."""
    if not settings.r2_endpoint:
        log.info("Skipping image enrichment (no R2 credentials)")
        return pkg

    html = pkg.article_html
    markers = list(_MARKER_RE.finditer(html))

    if not markers:
        log.info("No image markers found in '{}'", pkg.article_title)
        return pkg

    source_urls = pkg.topic.source_urls if pkg.topic else []
    source_queries = pkg.topic.source_queries if pkg.topic else []
    images: list[dict] = []

    for m in reversed(markers):
        img_type = m.group(1).lower()
        desc = m.group(2).strip()

        figure_html = ""
        try:
            if img_type == "chart":
                chart_url = await _resolve_chart(desc)
                if chart_url:
                    figure_html = _build_figure(chart_url, desc)
                    images.append({"type": "chart", "url": chart_url, "desc": desc})

            elif img_type == "evidence":
                evidence_url = await _resolve_evidence(desc, source_urls, source_queries)
                if evidence_url:
                    figure_html = _build_figure(evidence_url, desc)
                    images.append({"type": "evidence", "url": evidence_url, "desc": desc})
                else:
                    chart_url = await _resolve_chart(desc)
                    if chart_url:
                        figure_html = _build_figure(chart_url, desc)
                        images.append({"type": "evidence_chart", "url": chart_url, "desc": desc})
                    elif settings.pexels_api_key:
                        pexels = await _resolve_pexels(desc)
                        if pexels:
                            figure_html = _build_figure(*pexels)
                            images.append({"type": "evidence_fallback", "url": pexels[0], "desc": desc})

            elif img_type in ("explanatory", "rhythm"):
                if settings.pexels_api_key:
                    pexels = await _resolve_pexels(desc)
                    if pexels:
                        figure_html = _build_figure(*pexels)
                        images.append({"type": img_type, "url": pexels[0], "desc": desc})

        except Exception as exc:
            log.debug("Image enrichment failed for '{}': {}", desc[:40], exc)

        if figure_html:
            html = html[:m.start()] + "\n" + figure_html + html[m.end():]
        else:
            html = html[:m.start()] + html[m.end():]

    pkg.article_html = html
    pkg.section_images = images
    log.info("Enriched '{}' with {} images ({} markers found)",
             pkg.article_title, len(images), len(markers))
    return pkg
