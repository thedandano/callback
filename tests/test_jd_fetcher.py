"""Tests for callback.jd_fetcher (Playwright + trafilatura)."""

import asyncio
import json
import subprocess
import sys
from unittest.mock import AsyncMock, Mock

import pytest

import callback.jd_fetcher as jd_fetcher

_ARTICLE = (
    "<html><head><title>Senior Python Engineer - ExampleCo</title></head><body>"
    "<nav><a href='/'>Home</a><a href='/jobs'>All jobs</a><span>nav-link-text</span></nav>"
    "<main><article><h1>Senior Python Engineer</h1>"
    + "".join(
        f"<p>Paragraph {i}: You will design and ship Python services on Kubernetes, "
        "own reliability for the ingestion pipeline, and mentor engineers across "
        "the platform team while keeping latency under budget. You will also "
        "partner with product managers, write design documents, and run "
        "incident reviews so the on-call rotation gets calmer every quarter.</p>"
        for i in range(20)
    )
    + "<h2>Requirements</h2><ul><li>5+ years Python</li><li>Kubernetes</li><li>Go</li></ul>"
    "</article></main><footer>© ExampleCo</footer></body></html>"
)


def _events(caplog) -> list[dict]:
    return [json.loads(r.message) for r in caplog.records if r.name == "callback.jd_fetcher"]


# --- extract_markdown -------------------------------------------------------


def test_extract_markdown_uses_trafilatura_on_rich_page():
    markdown = jd_fetcher.extract_markdown(_ARTICLE, "body text", "https://example.com/job")

    actual = {
        "has_title": "Senior Python Engineer" in markdown,
        "has_requirement": "Kubernetes" in markdown,
        "nav_stripped": "nav-link-text" not in markdown,
        "long_enough": len(markdown) >= jd_fetcher.MIN_EXTRACT_CHARS,
        "is_body_text": markdown == "body text",
    }
    expected = {
        "has_title": True,
        "has_requirement": True,
        "nav_stripped": True,
        "long_enough": True,
        "is_body_text": False,
    }
    assert actual == expected


def test_extract_markdown_falls_back_to_body_text_when_thin(caplog):
    caplog.set_level("INFO", logger="callback.jd_fetcher")
    thin_html = "<html><body><p>Apply now.</p></body></html>"
    body_text = "Senior Python Engineer\n" + ("Build APIs and ship reliable systems. " * 60)

    markdown = jd_fetcher.extract_markdown(thin_html, body_text, "https://example.com/job")

    actual = {"markdown": markdown, "events": _events(caplog)}
    expected = {
        "markdown": body_text,
        "events": [
            {
                "event": "fetch_thin_extraction",
                "url": "https://example.com/job",
                "extracted_chars": len(jd_fetcher._trafilatura_markdown(thin_html)),
                "body_chars": len(body_text),
            }
        ],
    }
    assert actual == expected


def test_extract_markdown_keeps_thin_extraction_when_body_is_shorter(caplog):
    caplog.set_level("INFO", logger="callback.jd_fetcher")
    thin_html = "<html><body><article><p>Apply now for this role.</p></article></body></html>"

    markdown = jd_fetcher.extract_markdown(thin_html, "x", "https://example.com/job")

    actual = {"markdown": markdown, "events": _events(caplog)}
    expected = {"markdown": jd_fetcher._trafilatura_markdown(thin_html), "events": []}
    assert actual == expected


# --- cap_jd_text ------------------------------------------------------------


def test_cap_jd_text_truncates_and_logs(caplog):
    caplog.set_level("INFO", logger="callback.jd_fetcher")
    text = "x" * (jd_fetcher.MAX_JD_CHARS + 5)

    capped = jd_fetcher.cap_jd_text(text, "https://example.com/job")

    actual = {"chars": len(capped), "events": _events(caplog)}
    expected = {
        "chars": jd_fetcher.MAX_JD_CHARS,
        "events": [
            {
                "event": "fetch_oversized",
                "url": "https://example.com/job",
                "original_chars": jd_fetcher.MAX_JD_CHARS + 5,
                "cap_chars": jd_fetcher.MAX_JD_CHARS,
            }
        ],
    }
    assert actual == expected


def test_cap_jd_text_passes_short_text_unchanged(caplog):
    caplog.set_level("INFO", logger="callback.jd_fetcher")

    capped = jd_fetcher.cap_jd_text("short", "https://example.com/job")

    actual = {"text": capped, "events": _events(caplog)}
    expected = {"text": "short", "events": []}
    assert actual == expected


# --- fetch_url_to_markdown (Playwright wiring, browser faked) ----------------


class _FakePage:
    def __init__(self, calls: dict, html: str, body_text: str, goto_error=None, goto_delay=0.0):
        self._calls = calls
        self._html = html
        self._body_text = body_text
        self._goto_error = goto_error
        self._goto_delay = goto_delay

    async def goto(self, url, **kwargs):
        self._calls["goto"] = {"url": url, **kwargs}
        if self._goto_delay:
            await asyncio.sleep(self._goto_delay)
        if self._goto_error:
            raise self._goto_error

    async def wait_for_timeout(self, ms):
        self._calls["settle_ms"] = ms

    async def content(self):
        return self._html

    async def evaluate(self, script):
        self._calls["evaluate"] = script
        return self._body_text


def _fake_playwright(monkeypatch, html="<html></html>", body_text="", **page_kwargs) -> dict:
    """Install a fake async_playwright; return the dict of recorded calls."""
    calls: dict = {}
    page = _FakePage(calls, html, body_text, **page_kwargs)

    context = Mock()
    context.new_page = AsyncMock(return_value=page)
    browser = Mock()
    browser.new_context = AsyncMock(
        side_effect=lambda **kw: calls.__setitem__("new_context", kw) or context
    )
    browser.close = AsyncMock(side_effect=lambda: calls.__setitem__("closed", True))
    chromium = Mock()
    chromium.launch = AsyncMock(side_effect=lambda **kw: calls.__setitem__("launch", kw) or browser)
    playwright = Mock(chromium=chromium)

    manager = Mock()
    manager.__aenter__ = AsyncMock(return_value=playwright)
    manager.__aexit__ = AsyncMock(return_value=None)
    monkeypatch.setattr(jd_fetcher, "async_playwright", lambda: manager)
    return calls


def test_fetch_url_to_markdown_wires_playwright_and_extracts(monkeypatch):
    monkeypatch.delenv("CALLBACK_FETCH_PAGE_TIMEOUT_MS", raising=False)
    monkeypatch.delenv("CALLBACK_FETCH_OUTER_TIMEOUT_S", raising=False)
    calls = _fake_playwright(monkeypatch, html="<html>page</html>", body_text="body")
    monkeypatch.setattr(
        jd_fetcher,
        "extract_markdown",
        lambda html, body_text, url: f"md({html},{body_text},{url})",
    )

    markdown = asyncio.run(jd_fetcher.fetch_url_to_markdown("https://example.com/job"))

    actual = {"markdown": markdown, **calls}
    expected = {
        "markdown": "md(<html>page</html>,body,https://example.com/job)",
        "launch": {"headless": True, "args": ["--no-sandbox"]},
        "new_context": {"user_agent": jd_fetcher.USER_AGENT, "viewport": jd_fetcher.VIEWPORT},
        "goto": {
            "url": "https://example.com/job",
            "wait_until": "domcontentloaded",
            "timeout": jd_fetcher.DEFAULT_PAGE_TIMEOUT_MS,
        },
        "settle_ms": jd_fetcher.SETTLE_MS,
        "evaluate": jd_fetcher._BODY_TEXT_SCRIPT,
        "closed": True,
    }
    assert actual == expected


def test_fetch_url_to_markdown_applies_cap(monkeypatch):
    _fake_playwright(monkeypatch)
    monkeypatch.setattr(
        jd_fetcher, "extract_markdown", lambda *_: "y" * (jd_fetcher.MAX_JD_CHARS + 1)
    )

    markdown = asyncio.run(jd_fetcher.fetch_url_to_markdown("https://example.com/job"))

    assert len(markdown) == jd_fetcher.MAX_JD_CHARS


def test_fetch_url_to_markdown_honors_env_overrides(monkeypatch):
    monkeypatch.setenv("CALLBACK_FETCH_PAGE_TIMEOUT_MS", "15000")
    monkeypatch.setenv("CALLBACK_FETCH_OUTER_TIMEOUT_S", "5")
    calls = _fake_playwright(monkeypatch)
    monkeypatch.setattr(jd_fetcher, "extract_markdown", lambda *_: "ok")

    asyncio.run(jd_fetcher.fetch_url_to_markdown("https://example.com/job"))

    assert calls["goto"]["timeout"] == 15000


def test_fetch_url_to_markdown_closes_browser_and_propagates_goto_error(monkeypatch):
    expected_error = RuntimeError("net::ERR_NAME_NOT_RESOLVED")
    calls = _fake_playwright(monkeypatch, goto_error=expected_error)

    with pytest.raises(RuntimeError) as exc_info:
        asyncio.run(jd_fetcher.fetch_url_to_markdown("https://example.com/job"))

    actual = {"error": exc_info.value, "closed": calls.get("closed")}
    expected = {"error": expected_error, "closed": True}
    assert actual == expected


def test_fetch_url_to_markdown_propagates_outer_timeout(monkeypatch):
    monkeypatch.setattr(jd_fetcher, "_outer_timeout_s", lambda: 0.01)
    _fake_playwright(monkeypatch, goto_delay=1.0)

    with pytest.raises(asyncio.TimeoutError):
        asyncio.run(jd_fetcher.fetch_url_to_markdown("https://example.com/job"))


# --- import cost -------------------------------------------------------------


def test_importing_jd_fetcher_does_not_import_trafilatura():
    """trafilatura is imported lazily inside the fetch so server start-up does not pay for it."""
    code = "import sys, callback.jd_fetcher; print('trafilatura' in sys.modules)"
    out = subprocess.run(
        [sys.executable, "-c", code], capture_output=True, text=True, check=True
    ).stdout.strip()
    assert out == "False"
