from __future__ import annotations

import uuid

from loguru import logger as log
from playwright.async_api import async_playwright

from src.storage.r2_client import upload_image

_VIEWPORT = {"width": 1280, "height": 900}
_TIMEOUT = 20_000

_BLOCK_KEYWORDS = [
    "blocked", "access denied", "captcha", "security check",
    "please verify", "cloudflare", "attention required",
    "just a moment", "checking your browser", "bot detection",
    "unusual traffic", "are you a robot", "forbidden",
    "rate limit", "too many requests",
]

_USER_AGENT = (
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
    "AppleWebKit/537.36 (KHTML, like Gecko) "
    "Chrome/124.0.0.0 Safari/537.36"
)


async def _is_blocked(page) -> bool:
    """Check if the page shows a block/captcha instead of real content."""
    try:
        title = (await page.title()).lower()
        body_text = await page.inner_text("body")
        body_lower = body_text[:2000].lower()

        for kw in _BLOCK_KEYWORDS:
            if kw in title or kw in body_lower:
                log.debug("Page blocked (matched '{}'): {}", kw, page.url)
                return True

        if len(body_text.strip()) < 100:
            log.debug("Page too empty ({}chars), likely blocked: {}", len(body_text.strip()), page.url)
            return True

    except Exception:
        pass
    return False


async def capture_url(url: str, selector: str | None = None) -> bytes | None:
    """Take a screenshot of a URL. Returns None if blocked or failed."""
    try:
        async with async_playwright() as p:
            browser = await p.chromium.launch(headless=True)
            context = await browser.new_context(
                viewport=_VIEWPORT,
                user_agent=_USER_AGENT,
                locale="en-US",
                timezone_id="America/New_York",
                extra_http_headers={
                    "Accept-Language": "en-US,en;q=0.9",
                    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
                    "DNT": "1",
                },
            )
            page = await context.new_page()

            resp = await page.goto(url, wait_until="networkidle", timeout=_TIMEOUT)

            if resp and resp.status >= 400:
                log.debug("Screenshot HTTP {}: {}", resp.status, url)
                await browser.close()
                return None

            await page.wait_for_timeout(1500)

            if await _is_blocked(page):
                await browser.close()
                return None

            if selector:
                el = page.locator(selector).first
                if await el.count() == 0:
                    log.debug("Selector '{}' not found on {}", selector, url)
                    await browser.close()
                    return None
                img_bytes = await el.screenshot(type="png")
            else:
                img_bytes = await page.screenshot(type="png", full_page=False)

            await browser.close()
            return img_bytes
    except Exception as exc:
        log.debug("Screenshot failed for {}: {}", url, exc)
        return None


async def capture_google_trends(query: str) -> bytes | None:
    url = f"https://trends.google.com/trends/explore?q={query}&date=now%207-d"
    result = await capture_url(url, selector='[class*="interest-over-time"]')
    if result:
        return result
    return await capture_url(url)


async def capture_reddit_post(url: str) -> bytes | None:
    if not url.startswith("http"):
        return None
    old_url = url.replace("www.reddit.com", "old.reddit.com")
    return await capture_url(old_url, selector=".thing")


async def screenshot_and_upload(
    capture_fn, *args, filename_prefix: str = "evidence"
) -> str | None:
    """Capture screenshot and upload to R2. Returns public URL or None."""
    img_bytes = await capture_fn(*args)
    if not img_bytes:
        return None
    filename = f"{filename_prefix}-{uuid.uuid4().hex[:8]}.png"
    try:
        public_url = upload_image(img_bytes, filename)
        return public_url
    except Exception as exc:
        log.debug("Failed to upload screenshot: {}", exc)
        return None
