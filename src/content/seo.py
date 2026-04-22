from __future__ import annotations

import json
import re
from datetime import datetime, timezone

from src.config import settings
from src.storage.models import ContentPackage


def _estimate_word_count(html: str) -> int:
    text = re.sub(r"<[^>]+>", " ", html)
    return len(text.split())


def _estimate_reading_minutes(word_count: int) -> int:
    return max(1, round(word_count / 230))


def build_jsonld(pkg: ContentPackage, canonical_url: str) -> str:
    """Build a JSON-LD BlogPosting script tag for the article."""
    word_count = _estimate_word_count(pkg.article_html)

    schema = {
        "@context": "https://schema.org",
        "@type": "BlogPosting",
        "headline": pkg.article_title,
        "description": pkg.meta_description or "",
        "url": canonical_url,
        "datePublished": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%S+00:00"),
        "dateModified": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%S+00:00"),
        "wordCount": word_count,
        "timeRequired": f"PT{_estimate_reading_minutes(word_count)}M",
        "author": {
            "@type": "Organization",
            "name": "mockreal",
            "url": settings.website_api_url or "https://mockreal.com",
        },
        "publisher": {
            "@type": "Organization",
            "name": "mockreal",
            "url": settings.website_api_url or "https://mockreal.com",
        },
        "mainEntityOfPage": {
            "@type": "WebPage",
            "@id": canonical_url,
        },
        "inLanguage": "en-US",
    }

    if pkg.featured_image_url:
        schema["image"] = {
            "@type": "ImageObject",
            "url": pkg.featured_image_url,
        }

    if pkg.seo_keywords:
        schema["keywords"] = ", ".join(pkg.seo_keywords)

    compact = json.dumps(schema, ensure_ascii=False, separators=(",", ":"))
    return f'<script type="application/ld+json">{compact}</script>'


def build_canonical_tag(url: str) -> str:
    return f'<link rel="canonical" href="{url}" />'
