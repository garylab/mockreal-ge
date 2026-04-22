"""Enrich article HTML with images sourced from research pages, charts, or Pexels.

Image sources (in priority order):
1. Images extracted from fetched website/news/scholar pages (with source captions)
2. AI-generated data charts (matplotlib/seaborn)
3. Pexels stock images (fallback)
"""
from __future__ import annotations

import hashlib
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

_MARKER_RE = re.compile(
    r"<!--\s*IMG:(evidence|explanatory|rhythm|chart):(.+?)\s*-->", re.IGNORECASE
)


# ── Pexels helpers ────────────────────────────────────────────

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
    async with httpx.AsyncClient(timeout=30, follow_redirects=True) as client:
        resp = await client.get(url)
        resp.raise_for_status()
        return resp.content


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


# ── Source image extraction ───────────────────────────────────

async def _find_source_image(
    desc: str, source_images: list[dict],
) -> tuple[str, str, str] | None:
    """Pick and download a relevant image from pre-collected research source images.

    source_images: list of {url, alt, source_url, source_domain} from researcher.
    Returns (public_url, alt_text, source_caption) or None.
    """
    if not source_images:
        return None

    desc_lower = desc.lower()
    desc_words = set(desc_lower.split())

    # Score images by keyword overlap with the marker description
    scored = []
    for img in source_images:
        alt_words = set((img.get("alt", "") or "").lower().split())
        overlap = len(desc_words & alt_words)
        scored.append((overlap, img))
    scored.sort(key=lambda x: x[0], reverse=True)

    for _, img in scored[:5]:
        img_url = img.get("url", "")
        if not img_url.startswith("http"):
            continue
        try:
            async with httpx.AsyncClient(timeout=20, follow_redirects=True) as client:
                resp = await client.get(img_url, headers={"User-Agent": "Mozilla/5.0"})
                if resp.status_code != 200:
                    continue
                ctype = resp.headers.get("content-type", "")
                if "image" not in ctype:
                    continue
                if len(resp.content) < 5000:
                    continue
                h = hashlib.md5(resp.content).hexdigest()[:10]
                ext = "jpg" if "jpeg" in ctype else "png"
                filename = f"source-{h}.{ext}"
                public_url = upload_image(resp.content, filename)
                domain = img.get("source_domain", "") or "source"
                alt = img.get("alt", "") or desc
                return public_url, alt, f"Source: {domain}"
        except Exception:
            continue
    return None


# ── Chart generation ──────────────────────────────────────────

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


# ── HTML building ─────────────────────────────────────────────

def _build_figure(url: str, alt: str, caption: str = "", credit: str = "", credit_url: str = "") -> str:
    alt_safe = alt.replace('"', "&quot;")
    cap_parts: list[str] = []
    if caption:
        cap_parts.append(caption)
    if credit:
        link = f'<a href="{credit_url}">{credit}</a> on Pexels' if credit_url else credit
        cap_parts.append(f"Photo by {link}")
    figcaption = f"<figcaption>{' — '.join(cap_parts)}</figcaption>" if cap_parts else ""
    return (
        f'<figure><img src="{url}" alt="{alt_safe}" loading="lazy" width="800" />'
        f"{figcaption}</figure>"
    )


# ── Main enrichment ──────────────────────────────────────────

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

    source_images = pkg.source_images or []
    used_source_urls: set[str] = set()
    images: list[dict] = []

    for m in reversed(markers):
        img_type = m.group(1).lower()
        desc = m.group(2).strip()

        # Filter out already-used source images to avoid duplicates
        available_images = [i for i in source_images if i.get("url") not in used_source_urls]

        figure_html = ""
        try:
            if img_type == "chart":
                chart_url = await _resolve_chart(desc)
                if chart_url:
                    figure_html = _build_figure(chart_url, desc)
                    images.append({"type": "chart", "url": chart_url, "desc": desc})

            elif img_type == "evidence":
                source_img = await _find_source_image(desc, available_images)
                if source_img:
                    public_url, alt, caption = source_img
                    figure_html = _build_figure(public_url, alt, caption=caption)
                    images.append({"type": "source", "url": public_url, "desc": desc})
                    used_source_urls.add(public_url)
                else:
                    chart_url = await _resolve_chart(desc)
                    if chart_url:
                        figure_html = _build_figure(chart_url, desc)
                        images.append({"type": "evidence_chart", "url": chart_url, "desc": desc})
                    elif settings.pexels_api_key:
                        pexels = await _resolve_pexels(desc)
                        if pexels:
                            url, alt, credit, credit_url = pexels
                            figure_html = _build_figure(url, alt, credit=credit, credit_url=credit_url)
                            images.append({"type": "pexels_fallback", "url": url, "desc": desc})

            elif img_type in ("explanatory", "rhythm"):
                source_img = await _find_source_image(desc, available_images)
                if source_img:
                    public_url, alt, caption = source_img
                    figure_html = _build_figure(public_url, alt, caption=caption)
                    images.append({"type": "source", "url": public_url, "desc": desc})
                    used_source_urls.add(public_url)
                elif settings.pexels_api_key:
                    pexels = await _resolve_pexels(desc)
                    if pexels:
                        url, alt, credit, credit_url = pexels
                        figure_html = _build_figure(url, alt, credit=credit, credit_url=credit_url)
                        images.append({"type": img_type, "url": url, "desc": desc})

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
