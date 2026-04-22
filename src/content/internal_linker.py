from __future__ import annotations

import re

from loguru import logger as log

from src.config import settings
from src.storage import database as db
from src.storage.models import ContentPackage


def _slugify(title: str) -> str:
    slug = title.lower().strip()
    slug = re.sub(r"[^\w\s-]", "", slug)
    slug = re.sub(r"[\s_]+", "-", slug)
    return slug[:80].strip("-")


async def inject_internal_links(
    pkg: ContentPackage,
    title_embedding: list[float],
) -> ContentPackage:
    """Find related published articles and insert internal links into the article HTML."""
    if not title_embedding or not pkg.article_html:
        return pkg

    related = await db.find_related_published(
        embedding=title_embedding,
        exclude_id=pkg.content_id,
        limit=3,
    )

    if not related:
        log.debug("No related articles found for internal linking: '{}'", pkg.article_title)
        return pkg

    base_url = settings.website_api_url or ""

    links_html = []
    for r in related:
        slug = _slugify(r["title"])
        url = f"{base_url}/blog/{slug}"
        links_html.append(
            f'<li><a href="{url}" rel="nofollow noopener noreferrer" target="_blank">{r["title"]}</a></li>'
        )

    if not links_html:
        return pkg

    related_section = (
        '\n<aside class="related-posts">'
        "<h3>Related reading</h3>"
        f'<ul>{"".join(links_html)}</ul>'
        "</aside>\n"
    )

    cta_pattern = r'(<div class="cta">)'
    if re.search(cta_pattern, pkg.article_html):
        pkg.article_html = re.sub(cta_pattern, related_section + r"\1", pkg.article_html, count=1)
    else:
        pkg.article_html += related_section

    log.info("Injected {} internal links into '{}'", len(links_html), pkg.article_title)
    return pkg
