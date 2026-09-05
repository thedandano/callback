"""Fetch a job description page with Playwright and reduce it to markdown with trafilatura.

Playwright is already required for PDF rendering, so fetching adds no browser
dependency. trafilatura is imported lazily, in a short-lived child process, so
importing the server does not pay for it and a stuck extraction can be killed.
"""

from __future__ import annotations

import asyncio
import json
import logging
import multiprocessing
import os
import time
from collections.abc import Callable
from multiprocessing.connection import Connection
from typing import Any

from playwright.async_api import ViewportSize, async_playwright

logger = logging.getLogger("callback.jd_fetcher")

DEFAULT_PAGE_TIMEOUT_MS = 30_000
DEFAULT_OUTER_TIMEOUT_S = 35
SETTLE_MS = 2_500
# Bound on each browser/driver cleanup step after a fetch or a timeout.
CLOSE_TIMEOUT_S = 5.0
USER_AGENT = (
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/128.0.0.0 Safari/537.36"
)
VIEWPORT: ViewportSize = {"width": 1280, "height": 900}
# Token counts are estimated at 4 characters per token; no tokenizer dependency.
CHARS_PER_TOKEN = 4
MIN_EXTRACT_CHARS = 300 * CHARS_PER_TOKEN
MAX_JD_CHARS = 4_000 * CHARS_PER_TOKEN
# When capping, prefer a line break at most this far before the cap; further back
# would drop real content (e.g. a title line followed by one long paragraph).
CAP_LINE_SLACK_CHARS = 1_000
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


# --- extraction (runs in a killable child process) ---------------------------


def _trafilatura_markdown(html: str) -> str:
    import trafilatura  # lazy: keeps server import time down

    return (
        trafilatura.extract(html, output_format="markdown", favor_recall=True, include_tables=True)
        or ""
    )


def _extract_worker(conn: Connection, html: str) -> None:
    """Child-process entry point: send ("ok", markdown) or ("error", message)."""
    try:
        conn.send(("ok", _trafilatura_markdown(html)))
    except Exception as exc:
        conn.send(("error", f"{type(exc).__name__}: {exc}"))
    finally:
        conn.close()


def run_killable(worker: Callable[[Connection, Any], None], arg: Any, timeout_s: float) -> str:
    """Run worker(conn, arg) in a spawned child and kill it when timeout_s expires.

    trafilatura cannot be interrupted in-process. A child process can be killed,
    so a hung or oversized extraction reclaims its CPU and memory at the deadline
    instead of lingering in the stdio server.
    """
    ctx = multiprocessing.get_context("spawn")
    parent, child = ctx.Pipe(duplex=False)
    proc = ctx.Process(target=worker, args=(child, arg), daemon=True)
    proc.start()
    child.close()
    try:
        if not parent.poll(max(timeout_s, 0.0)):
            raise TimeoutError(f"extraction exceeded {timeout_s:.1f}s; worker killed")
        try:
            status, payload = parent.recv()
        except EOFError as exc:
            raise RuntimeError("extraction worker exited without a result") from exc
    finally:
        parent.close()
        if proc.is_alive():
            proc.kill()
        proc.join(timeout=1.0)
    if status != "ok":
        raise RuntimeError(f"extraction failed: {payload}")
    return payload


def extract_markdown(extracted: str, body_text: str, url: str) -> str:
    """Choose the JD text from trafilatura's extraction and the page body text.

    A thin extraction (under MIN_EXTRACT_CHARS) falls back to the body text only
    when the body itself is substantive, so a login wall or empty SPA shell is
    not promoted to a job description. Anything still thin is rejected, which
    jd_fetch reports as a fetch failure. Both decisions are logged.
    """
    result = extracted
    if len(extracted) < MIN_EXTRACT_CHARS and len(body_text) >= MIN_EXTRACT_CHARS:
        _log(
            "fetch_thin_extraction",
            url=url,
            extracted_chars=len(extracted),
            body_chars=len(body_text),
        )
        result = body_text
    if len(result) < MIN_EXTRACT_CHARS:
        _log(
            "fetch_thin",
            url=url,
            extracted_chars=len(extracted),
            body_chars=len(body_text),
            min_chars=MIN_EXTRACT_CHARS,
        )
        raise RuntimeError(f"thin page: {len(result)} chars, under the {MIN_EXTRACT_CHARS} minimum")
    return result


def cap_jd_text(text: str, url: str) -> str:
    """Hard-cap the JD at MAX_JD_CHARS, cutting at the last newline when one exists."""
    if len(text) <= MAX_JD_CHARS:
        return text
    cut = text.rfind("\n", MAX_JD_CHARS - CAP_LINE_SLACK_CHARS, MAX_JD_CHARS)
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
    if len(markdown.strip()) <= MIN_MARKDOWN_CHARS:
        return markdown  # thin content stays thin so jd_fetch rejects it as empty
    if not title or title.lower() in markdown.lower():
        return markdown
    return f"# {title}\n\n{markdown}"


# --- browser ----------------------------------------------------------------


async def _cleanup(step: str, coro: Any, url: str) -> None:
    """Await a cleanup step with its own bound; a hung step is logged, not waited on."""
    try:
        await asyncio.wait_for(coro, timeout=CLOSE_TIMEOUT_S)
    except Exception as exc:
        # ponytail: a driver that ignores stop() leaks a process; kill it via the
        # driver transport if that is ever observed.
        _log("browser_cleanup_failed", url=url, step=step, error_class=type(exc).__name__)


async def _load_page(url: str) -> tuple[str, str, str]:
    """Return (html, body_text, title) for url using a normal Chrome user agent."""
    playwright = await async_playwright().start()
    browser = None
    try:
        browser = await playwright.chromium.launch(headless=True, args=["--no-sandbox"])
        context = await browser.new_context(user_agent=USER_AGENT, viewport=VIEWPORT)
        page = await context.new_page()
        response = await page.goto(url, wait_until="domcontentloaded", timeout=_page_timeout_ms())
        status = response.status if response else None
        _log("fetch_status", url=url, status=status)
        if status is None or not 200 <= status < 300:
            raise RuntimeError(f"http status {status}")
        await page.wait_for_timeout(SETTLE_MS)
        html = await page.content()
        body_text = await page.evaluate(_BODY_TEXT_SCRIPT)
        title = await page.title()
    finally:
        if browser is not None:
            await _cleanup("browser.close", browser.close(), url)
        await _cleanup("playwright.stop", playwright.stop(), url)
    return html, body_text, title


async def _fetch_url_to_markdown_unbounded(url: str, deadline: float) -> str:
    html, body_text, title = await _load_page(url)
    remaining = deadline - time.monotonic()
    extracted = await asyncio.to_thread(run_killable, _extract_worker, html, remaining)
    markdown = extract_markdown(extracted, body_text, url)
    return cap_jd_text(_with_title(markdown, title), url)


async def fetch_url_to_markdown(url: str) -> str:
    """Fetch a URL and return its job description as capped markdown.

    The outer timeout bounds the whole operation: page load, bounded browser
    cleanup, and a killable extraction that is given only the time left.
    """
    timeout = _outer_timeout_s()
    return await asyncio.wait_for(
        _fetch_url_to_markdown_unbounded(url, time.monotonic() + timeout),
        timeout=timeout,
    )
