"""Research a topic before writing by gathering data from multiple sources.

Sources:
1. Google Search — top organic results (competitors to beat)
2. Google News — fresh/timely angles
3. Google Scholar — academic papers and data (PDFs downloaded + parsed)

All scraped via Serper.dev (pages) and SerpAPI (search/news/scholar).
"""
from __future__ import annotations

import asyncio
import re

import httpx
from loguru import logger as log

from src.config import settings
from src.utils import serpapi_client
from src.utils.ai_client import chat_gpt

_MD_IMAGE_RE = re.compile(r"!\[([^\]]*)\]\(([^\s)\"']+)")
_MIN_IMAGE_URL_LEN = 20


# ── Scraping helpers ──────────────────────────────────────────

def _extract_images_from_markdown(md: str) -> list[dict]:
    """Extract image URLs and alt text from markdown content."""
    images: list[dict] = []
    seen: set[str] = set()
    for alt, url in _MD_IMAGE_RE.findall(md):
        url = url.strip()
        if (
            len(url) < _MIN_IMAGE_URL_LEN
            or url in seen
            or not url.startswith("http")
            or url.endswith(".svg")
            or "logo" in url.lower()
            or "icon" in url.lower()
            or "avatar" in url.lower()
            or "badge" in url.lower()
            or "1x1" in url
        ):
            continue
        seen.add(url)
        images.append({"url": url, "alt": alt or ""})
    return images


async def _scrape_url(url: str) -> dict:
    """Scrape a URL using Serper.dev scrape API with markdown.

    Returns {"text": str, "images": list[dict]} where images have url + alt.
    """
    if not settings.serper_api_key:
        return {"text": "", "images": []}
    try:
        async with httpx.AsyncClient(timeout=45) as client:
            resp = await client.post(
                "https://scrape.serper.dev",
                headers={
                    "X-API-KEY": settings.serper_api_key,
                    "Content-Type": "application/json",
                },
                json={"url": url, "includeMarkdown": True},
            )
            if resp.status_code != 200:
                return {"text": "", "images": []}
            data = resp.json()
            text = (data.get("text", "") or "")[:6000]
            md = data.get("markdown", "") or ""
            images = _extract_images_from_markdown(md)
            return {"text": text, "images": images}
    except Exception as exc:
        log.debug("Serper scrape failed for {}: {}", url, exc)
        return {"text": "", "images": []}


async def _download_pdf(url: str) -> bytes:
    """Download a PDF file, return raw bytes."""
    try:
        async with httpx.AsyncClient(timeout=60, follow_redirects=True) as client:
            resp = await client.get(url)
            if resp.status_code != 200:
                return b""
            content_type = resp.headers.get("content-type", "")
            if "pdf" not in content_type and not url.lower().endswith(".pdf"):
                return b""
            return resp.content
    except Exception as exc:
        log.debug("PDF download failed for {}: {}", url, exc)
        return b""


def _parse_pdf(pdf_bytes: bytes, max_chars: int = 8000) -> str:
    """Extract text from a PDF using PyMuPDF."""
    if not pdf_bytes:
        return ""
    try:
        import pymupdf
        doc = pymupdf.open(stream=pdf_bytes, filetype="pdf")
        text_parts: list[str] = []
        total = 0
        for page in doc:
            page_text = page.get_text()
            text_parts.append(page_text)
            total += len(page_text)
            if total >= max_chars:
                break
        doc.close()
        return "\n".join(text_parts)[:max_chars]
    except Exception as exc:
        log.debug("PDF parse failed: {}", exc)
        return ""


async def _fetch_scholar_paper(url: str) -> str:
    """Try to download and parse a scholar paper PDF. Falls back to scraping."""
    pdf_bytes = await _download_pdf(url)
    if pdf_bytes:
        text = _parse_pdf(pdf_bytes)
        if text and len(text) > 200:
            return text

    result = await _scrape_url(url)
    return result["text"] if isinstance(result, dict) else result


# ── Source fetchers ───────────────────────────────────────────

async def _research_search(query: str) -> list[dict]:
    """Fetch Google Search results + scrape top pages."""
    data = await serpapi_client.google_search(query)
    organic = data.get("organic_results", [])[:8]

    sources: list[dict] = []
    for item in organic:
        sources.append({
            "title": item.get("title", ""),
            "url": item.get("link", ""),
            "snippet": item.get("snippet", "")[:300],
            "type": "search",
        })

    if not sources:
        return []

    scrape_tasks = [_scrape_url(s["url"]) for s in sources[:5]]
    page_results = await asyncio.gather(*scrape_tasks, return_exceptions=True)

    for src, result in zip(sources[:5], page_results):
        if isinstance(result, Exception) or not result:
            src["full_text"] = ""
            src["images"] = []
        else:
            src["full_text"] = result["text"][:5000]
            src["images"] = result.get("images", [])

    return sources


async def _research_news(query: str) -> list[dict]:
    """Fetch Google News results + scrape articles for fresh angles."""
    data = await serpapi_client.google_news(query)
    news_items = data.get("news_results", [])[:6]

    sources: list[dict] = []
    for item in news_items:
        source_val = item.get("source", "")
        source_name = source_val.get("name", "") if isinstance(source_val, dict) else str(source_val)
        sources.append({
            "title": item.get("title", ""),
            "url": item.get("link", ""),
            "snippet": (item.get("snippet", "") or "")[:300],
            "type": "news",
            "date": item.get("date", ""),
            "source_name": source_name,
        })

    # top_stories contain curated high-quality articles
    for group in data.get("top_stories", []):
        for story in group.get("stories", []):
            sources.append({
                "title": story.get("title", ""),
                "url": story.get("link", ""),
                "snippet": "",
                "type": "news",
                "date": story.get("date", ""),
                "source_name": story.get("source", ""),
            })

    if not sources:
        return []

    scrape_tasks = [_scrape_url(s["url"]) for s in sources[:4]]
    page_results = await asyncio.gather(*scrape_tasks, return_exceptions=True)

    for src, result in zip(sources[:4], page_results):
        if isinstance(result, Exception) or not result:
            src["full_text"] = ""
            src["images"] = []
        else:
            src["full_text"] = result["text"][:4000]
            src["images"] = result.get("images", [])

    return sources


async def _research_scholar(query: str) -> list[dict]:
    """Fetch Google Scholar results, download PDFs and parse them."""
    data = await serpapi_client.google_scholar(query)
    results = data.get("organic_results", [])[:5]

    sources: list[dict] = []
    for item in results:
        # 1. Check resources[] for explicit PDF links
        pdf_url = ""
        for resource in item.get("resources", []):
            fmt = resource.get("file_format", "").upper()
            if fmt == "PDF":
                pdf_url = resource.get("link", "")
                break

        # 2. If top-level type is "Pdf", the main link IS the PDF
        item_type = item.get("type", "")
        if not pdf_url and item_type.lower() == "pdf":
            pdf_url = item.get("link", "")

        # 3. HTML version as a scrape-friendly fallback
        html_url = item.get("inline_links", {}).get("html_version", "")

        # Pick the best URL: PDF for parsing, HTML for scraping, main link as last resort
        main_url = item.get("link", "")
        display_url = pdf_url or html_url or main_url

        sources.append({
            "title": item.get("title", ""),
            "url": display_url,
            "main_url": main_url,
            "pdf_url": pdf_url,
            "html_url": html_url,
            "snippet": item.get("snippet", "")[:300],
            "type": "scholar",
            "authors": ", ".join(
                a.get("name", "") for a in item.get("publication_info", {}).get("authors", [])
            ),
            "year": item.get("publication_info", {}).get("summary", ""),
            "cited_by": item.get("inline_links", {}).get("cited_by", {}).get("total", 0),
            "is_pdf": bool(pdf_url),
        })

    if not sources:
        return []

    async def _fetch_scholar_content(src: dict) -> str:
        # Try PDF first
        if src.get("pdf_url"):
            text = await _fetch_scholar_paper(src["pdf_url"])
            if text and len(text) > 200:
                return text
        # Try HTML version (often full text on PMC, etc.)
        if src.get("html_url"):
            result = await _scrape_url(src["html_url"])
            text = result["text"] if isinstance(result, dict) else result
            if text and len(text) > 200:
                return text
        # Fall back to main link
        if src.get("main_url"):
            result = await _scrape_url(src["main_url"])
            return result["text"] if isinstance(result, dict) else result
        return ""

    fetch_tasks = [_fetch_scholar_content(s) for s in sources[:3]]
    paper_texts = await asyncio.gather(*fetch_tasks, return_exceptions=True)

    for src, text in zip(sources[:3], paper_texts):
        if isinstance(text, Exception) or not text:
            src["full_text"] = ""
        else:
            src["full_text"] = text[:6000]

    return sources


# ── Main research function ────────────────────────────────────

async def research_topic(topic_title: str) -> dict:
    """Research a topic using Google Search + News + Scholar in parallel.

    Returns:
        sources: list of {title, url, snippet, type, full_text, ...}
        research_brief: AI-generated synthesis
    """
    search_results, news_results, scholar_results = await asyncio.gather(
        _research_search(topic_title),
        _research_news(topic_title),
        _research_scholar(topic_title),
        return_exceptions=True,
    )

    if isinstance(search_results, Exception):
        log.warning("Search research failed for '{}': {}", topic_title, search_results)
        search_results = []
    if isinstance(news_results, Exception):
        log.warning("News research failed for '{}': {}", topic_title, news_results)
        news_results = []
    if isinstance(scholar_results, Exception):
        log.warning("Scholar research failed for '{}': {}", topic_title, scholar_results)
        scholar_results = []

    all_sources = search_results + news_results + scholar_results

    if not all_sources:
        log.warning("Research: no results for '{}'", topic_title)
        return {"sources": [], "research_brief": ""}

    # Build blocks for synthesis
    blocks: list[str] = []

    if search_results:
        blocks.append("=== GOOGLE SEARCH (competitors) ===")
        for s in search_results[:5]:
            text = s.get("full_text", "")
            if text and len(text) > 100:
                blocks.append(f"[{s['title']}]({s['url']}):\n{text[:4000]}")
            else:
                blocks.append(f"[{s['title']}]({s['url']}): {s['snippet']}")

    if news_results:
        blocks.append("\n=== GOOGLE NEWS (fresh angles) ===")
        for s in news_results[:4]:
            date_str = f" ({s.get('date', '')})" if s.get("date") else ""
            source_str = f" — {s.get('source_name', '')}" if s.get("source_name") else ""
            text = s.get("full_text", "")
            if text and len(text) > 100:
                blocks.append(f"[{s['title']}]{source_str}{date_str}({s['url']}):\n{text[:3000]}")
            else:
                blocks.append(f"[{s['title']}]{source_str}{date_str}({s['url']}): {s['snippet']}")

    if scholar_results:
        blocks.append("\n=== GOOGLE SCHOLAR (academic/data) ===")
        for s in scholar_results[:3]:
            authors = f" by {s.get('authors', '')}" if s.get("authors") else ""
            cited = f" [cited {s.get('cited_by', 0)}x]" if s.get("cited_by") else ""
            text = s.get("full_text", "")
            if text and len(text) > 200:
                blocks.append(f"[{s['title']}]{authors}{cited}({s['url']}):\n{text[:5000]}")
            else:
                blocks.append(f"[{s['title']}]{authors}{cited}({s['url']}): {s['snippet']}")

    combined = "\n\n---\n\n".join(blocks)

    brief = await chat_gpt(
        messages=[{"role": "user", "content": (
            f"Topic: \"{topic_title}\"\n\n"
            "Below are results from Google Search (competitors), Google News (fresh), "
            "and Google Scholar (academic). Synthesize them into a research brief:\n\n"
            "1. KEY FACTS and DATA POINTS. Only specific, verifiable claims. "
            "Note which source said what.\n"
            "2. CONSENSUS: what do most sources agree on?\n"
            "3. FRESH NEWS: what happened recently that's relevant? "
            "Include dates and names.\n"
            "4. ACADEMIC FINDINGS: any research data, studies, or statistics "
            "from the scholar results?\n"
            "5. GAPS: what do ALL these sources miss? What angle is nobody covering?\n"
            "6. CONTRADICTIONS: where do sources disagree?\n"
            "7. Specific STATISTICS, NAMES, COMPANIES, DATES mentioned.\n\n"
            "Be specific and cite sources. Keep under 1000 words.\n\n"
            f"SOURCES:\n{combined}"
        )}],
        temperature=0.3,
        max_tokens=2500,
    )

    log.info(
        "Research complete for '{}': {} search + {} news + {} scholar sources, {} chars brief",
        topic_title, len(search_results), len(news_results),
        len(scholar_results), len(brief),
    )

    # Collect all images discovered during scraping
    source_images: list[dict] = []
    for s in all_sources:
        page_url = s.get("url", "")
        domain = page_url.split("/")[2].replace("www.", "") if page_url.startswith("http") else ""
        for img in s.get("images", []):
            source_images.append({
                "url": img["url"],
                "alt": img.get("alt", ""),
                "source_url": page_url,
                "source_domain": domain,
            })

    return {
        "sources": all_sources,
        "research_brief": brief,
        "source_images": source_images,
    }
