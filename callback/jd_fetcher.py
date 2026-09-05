"""Fetch a job description page with Playwright and reduce it to markdown with trafilatura.

Playwright is already required for PDF rendering, so fetching adds no browser
dependency. trafilatura is imported lazily inside the fetch so importing the
server does not pay for it.
"""

from __future__ import annotations

import asyncio
import json
import logging
import os

from playwright.async_api import ViewportSize, async_playwright

logger = logging.getLogger("callback.jd_fetcher")

DEFAULT_PAGE_TIMEOUT_MS = 30_000
DEFAULT_OUTER_TIMEOUT_S = 35
SETTLE_MS = 2_500
USER_AGENT = (
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/128.0.0.0 Safari/537.36"
)
VIEWPORT: ViewportSize = {"width": 1280, "height": 900}
# Token counts are estimated at 4 characters per token; no tokenizer dependency.
CHARS_PER_TOKEN = 4
MIN_EXTRACT_CHARS = 300 * CHARS_PER_TOKEN
MAX_JD_CHARS = 4_000 * CHARS_PER_TOKEN
MIN_MARKDOWN_CHARS = 50
_BODY_TEXT_SCRIPT = "() => document.body ? document.body.innerText : ''"


class JDFetchError(Exception):
    """Domain error raised by graph nodes when JD fetch cannot be satisfied."""

    def __init__(self, reason: str, url: str, cause: Exception | None = None) -> None:
        self.reason = reason
        self.url = url
        self.cause = cause
        super().__init__(reason, url, cause)

    def __str__(self) -> str:
        return f"JDFetchError(reason={self.reason}, url={self.url}, cause={self.cause})"


def _page_timeout_ms() -> int:
    return int(os.getenv("CALLBACK_FETCH_PAGE_TIMEOUT_MS", DEFAULT_PAGE_TIMEOUT_MS))


def _outer_timeout_s() -> float:
    return float(os.getenv("CALLBACK_FETCH_OUTER_TIMEOUT_S", DEFAULT_OUTER_TIMEOUT_S))


def _log(event: str, **fields: object) -> None:
    logger.info(json.dumps({"event": event, **fields}))


def _trafilatura_markdown(html: str) -> str:
    import trafilatura  # lazy: keeps server import time down

    return (
        trafilatura.extract(html, output_format="markdown", favor_recall=True, include_tables=True)
        or ""
    )


def extract_markdown(html: str, body_text: str, url: str) -> str:
    """Reduce page HTML to markdown.

    A thin extraction (under MIN_EXTRACT_CHARS) falls back to the page's body
    text when that is longer, so a boilerplate-heavy page is not mistaken for
    an empty one. The fallback is logged.
    """
    extracted = _trafilatura_markdown(html)
    if len(extracted) < MIN_EXTRACT_CHARS and len(body_text) > len(extracted):
        _log(
            "fetch_thin_extraction",
            url=url,
            extracted_chars=len(extracted),
            body_chars=len(body_text),
        )
        return body_text
    return extracted


def cap_jd_text(text: str, url: str) -> str:
    """Hard-cap the JD at MAX_JD_CHARS, cutting at the last newline when one exists."""
    if len(text) <= MAX_JD_CHARS:
        return text
    cut = text.rfind("\n", 0, MAX_JD_CHARS)
    capped = text[: cut if cut > 0 else MAX_JD_CHARS]
    _log(
        "fetch_oversized",
        url=url,
        original_chars=len(text),
        cap_chars=MAX_JD_CHARS,
        kept_chars=len(capped),
    )
    return capped


def _with_title(markdown: str, title: str) -> str:
    """Prepend the page title as a heading when the extraction lost it.

    Leading '#' characters are dropped (some boards put one in the <title>), so
    the heading marker is never doubled.
    """
    title = title.strip().lstrip("#").strip()
    if not title or title.lower() in markdown.lower():
        return markdown
    return f"# {title}\n\n{markdown}"


async def _load_page(url: str) -> tuple[str, str, str]:
    """Return (html, body_text, title) for url using a normal Chrome user agent."""
    async with async_playwright() as p:
        browser = await p.chromium.launch(headless=True, args=["--no-sandbox"])
        try:
            context = await browser.new_context(user_agent=USER_AGENT, viewport=VIEWPORT)
            page = await context.new_page()
            response = await page.goto(
                url, wait_until="domcontentloaded", timeout=_page_timeout_ms()
            )
            status = response.status if response else None
            _log("fetch_status", url=url, status=status)
            if response is None or response.status >= 400:
                raise RuntimeError(f"http status {status}")
            await page.wait_for_timeout(SETTLE_MS)
            html = await page.content()
            body_text = await page.evaluate(_BODY_TEXT_SCRIPT)
            title = await page.title()
        finally:
            await browser.close()
    return html, body_text, title


async def _fetch_url_to_markdown_unbounded(url: str) -> str:
    html, body_text, title = await _load_page(url)
    markdown = _with_title(extract_markdown(html, body_text, url), title)
    return cap_jd_text(markdown, url)


async def fetch_url_to_markdown(url: str) -> str:
    """Fetch a URL and return its job description as capped markdown."""
    return await asyncio.wait_for(
        _fetch_url_to_markdown_unbounded(url),
        timeout=_outer_timeout_s(),
    )
