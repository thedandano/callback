# M3 — Replace the Fetcher: Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Ship W1 from `INTENT.md`: replace crawl4ai with Playwright plus trafilatura for job-description fetching, cap `jd_text` at 4,000 tokens, drop the two crawl4ai-only env vars, and turn the five measured job URLs into E1 fetch fixtures with their archived keywords as the recall golden.

**Architecture:** `callback/jd_fetcher.py` keeps its public surface (`fetch_url_to_markdown`, `JDFetchError`, `MIN_MARKDOWN_CHARS`, the page and outer timeouts) so `apply_nodes.jd_fetch` and `server.py` do not change. Inside, Playwright (already required for PDF rendering) loads the page with a normal Chrome user agent and a 1280×900 viewport, waits for `domcontentloaded` plus a 2.5 s settle, and hands the HTML to trafilatura (imported lazily, inside the fetch). Two pure helpers, `extract_markdown` and `cap_jd_text`, hold the thin-extraction fallback and the size cap so they are unit-testable without a browser. Fixtures live under `evals/extract/` in the shape M6 expects.

**Tech Stack:** Python 3.12, Playwright 1.59 (`playwright.async_api`), trafilatura (new runtime dependency), pytest, uv.

**Spec:** `INTENT.md` §"M3 — Replace the fetcher" (items 1–5 and "Done when"), `DECISIONS.md` Q2. Measured facts the spec rests on: on the five archived URLs Playwright + trafilatura matched crawl4ai's keyword recall within one term, returned 1.5x to 37x fewer tokens, and the one bot-check failure was the headless user-agent string.

## Global Constraints

- Tests assert whole objects: build `actual = {...}` and `expected = {...}` dicts and `assert actual == expected`. No piecemeal key checks. The pre-commit hook `expected-object assertions in Python tests` enforces this.
- ruff: line length 100, `max-complexity = 7`. `uv run ruff check .` and `uv run ruff format --check .` clean.
- `uv run pyright` 0 errors. `uv run pytest -q` green at every commit (658 at branch start).
- No silent failures: every fallback (thin extraction → body text) and every truncation (`fetch_oversized`) is logged as a JSON line on the `callback.jd_fetcher` logger with an `event` key.
- The public surface of `callback.jd_fetcher` used by other modules stays: `fetch_url_to_markdown(url) -> str` (async), `JDFetchError(reason, url, cause=None)`, `MIN_MARKDOWN_CHARS = 50`, env vars `CALLBACK_FETCH_PAGE_TIMEOUT_MS` (default 30000) and `CALLBACK_FETCH_OUTER_TIMEOUT_S` (default 35).
- Env vars `CALLBACK_FETCH_MAGIC` and `CALLBACK_FETCH_WAIT_UNTIL` are removed everywhere (code, tests, docs).
- Exact values from the spec: user agent `Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/128.0.0.0 Safari/537.36`; viewport `{"width": 1280, "height": 900}`; `wait_until="domcontentloaded"`; settle `2_500` ms; trafilatura call `trafilatura.extract(html, output_format="markdown", favor_recall=True, include_tables=True)`; thin threshold `300` tokens; hard cap `4_000` tokens; tokens are estimated at 4 characters each (`MIN_EXTRACT_CHARS = 1_200`, `MAX_JD_CHARS = 16_000`). No tiktoken.
- Tracing: nothing in this milestone touches LangSmith spans. Do not add JD text to any span or trace metadata.
- Do not touch tailor instructions, extraction protocol, or scoring.
- Live-network tests are marked `@pytest.mark.local` and never run in CI. Deterministic fixture tests run in CI.
- Commit trailer on every commit:
  ```
  Co-Authored-By: Claude Fable 5.1 <noreply@anthropic.com>
  Claude-Session: https://claude.ai/code/session_01CBmQfLDXe6dxY5JVQnvHcz
  ```

## File Structure

| File | Change |
|------|--------|
| `pyproject.toml`, `uv.lock` | remove `crawl4ai`; add `trafilatura`; add `evals` to pytest `testpaths` |
| `callback/jd_fetcher.py` | rewrite on Playwright + trafilatura; add `extract_markdown`, `cap_jd_text`; drop `_wait_until`, `_magic` |
| `tests/test_jd_fetcher.py` | rewrite: pure-helper tests with real trafilatura, Playwright wiring tests with fakes, lazy-import test |
| `evals/__init__.py`, `evals/extract/*.md`, `evals/extract/*.golden.json`, `evals/extract/sources.json` | five E1 fetch fixtures and their provenance |
| `evals/test_fetch_recall.py` | CI recall test on the stored fixtures; `local` live-fetch test |
| `scripts/smoke_apply.py` | optional `--url` argument so the smoke run exercises the fetcher |
| `.github/workflows/ci.yml`, `.pre-commit-config.yaml` | run pytest over `testpaths` (tests + evals) instead of `tests/` only |
| `CLAUDE.md`, `AGENTS.md`, `INTENT.md` | env-var docs, fetcher description, W1 fixed, M3 shipped |

---

### Task 1: Rewrite `jd_fetcher.py` on Playwright + trafilatura

**Files:**
- Modify: `pyproject.toml` (dependencies), `uv.lock`
- Modify: `callback/jd_fetcher.py` (full rewrite)
- Rewrite: `tests/test_jd_fetcher.py`

**Interfaces:**
- Consumes: `playwright.async_api.async_playwright` (already used by `callback/render/html_builder.py:187` with `p.chromium.launch(args=["--no-sandbox"])`).
- Produces (used by Tasks 2 and 3 and by existing callers):
  - `async def fetch_url_to_markdown(url: str) -> str` — unchanged signature.
  - `def extract_markdown(html: str, body_text: str, url: str) -> str` — pure; trafilatura with thin fallback.
  - `def cap_jd_text(text: str, url: str) -> str` — pure; hard cap with `fetch_oversized` log.
  - Constants: `USER_AGENT`, `VIEWPORT`, `SETTLE_MS`, `CHARS_PER_TOKEN = 4`, `MIN_EXTRACT_CHARS = 1_200`, `MAX_JD_CHARS = 16_000`, `MIN_MARKDOWN_CHARS = 50`, `DEFAULT_PAGE_TIMEOUT_MS = 30_000`, `DEFAULT_OUTER_TIMEOUT_S = 35`.
  - `JDFetchError` unchanged.

- [ ] **Step 1: Swap the dependency**

```bash
uv remove crawl4ai
uv add trafilatura
uv sync --all-groups
uv pip list | wc -l        # record the number in your report (was 148 lines with crawl4ai)
```

Confirm `pyproject.toml` no longer lists `crawl4ai` and lists `trafilatura`. Do not pin a lower bound tighter than what `uv add` writes.

- [ ] **Step 2: Write the failing tests**

Replace `tests/test_jd_fetcher.py` entirely with:

```python
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
        "the platform team while keeping latency under budget.</p>"
        for i in range(12)
    )
    + "<h2>Requirements</h2><ul><li>5+ years Python</li><li>Kubernetes</li><li>Go</li></ul>"
    "</article></main><footer>© ExampleCo</footer></body></html>"
)


def _events(caplog) -> list[dict]:
    return [
        json.loads(r.message) for r in caplog.records if r.name == "callback.jd_fetcher"
    ]


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
                "extracted_chars": len(
                    jd_fetcher._trafilatura_markdown(thin_html)
                ),
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
    chromium.launch = AsyncMock(
        side_effect=lambda **kw: calls.__setitem__("launch", kw) or browser
    )
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
```

- [ ] **Step 3: Run the tests to verify they fail**

Run: `uv run pytest tests/test_jd_fetcher.py -q`
Expected: FAIL with `AttributeError: module 'callback.jd_fetcher' has no attribute 'extract_markdown'` (and the module itself may fail to import because `crawl4ai` is gone).

- [ ] **Step 4: Rewrite `callback/jd_fetcher.py`**

```python
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

from playwright.async_api import async_playwright

logger = logging.getLogger("callback.jd_fetcher")

DEFAULT_PAGE_TIMEOUT_MS = 30_000
DEFAULT_OUTER_TIMEOUT_S = 35
SETTLE_MS = 2_500
USER_AGENT = (
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/128.0.0.0 Safari/537.36"
)
VIEWPORT = {"width": 1280, "height": 900}
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
        trafilatura.extract(
            html, output_format="markdown", favor_recall=True, include_tables=True
        )
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
    """Hard-cap the JD at MAX_JD_CHARS; log the original size when truncating."""
    if len(text) <= MAX_JD_CHARS:
        return text
    _log("fetch_oversized", url=url, original_chars=len(text), cap_chars=MAX_JD_CHARS)
    return text[:MAX_JD_CHARS]


async def _load_page(url: str) -> tuple[str, str]:
    """Return (html, body_text) for url using a normal Chrome user agent."""
    async with async_playwright() as p:
        browser = await p.chromium.launch(headless=True, args=["--no-sandbox"])
        try:
            context = await browser.new_context(user_agent=USER_AGENT, viewport=VIEWPORT)
            page = await context.new_page()
            await page.goto(url, wait_until="domcontentloaded", timeout=_page_timeout_ms())
            await page.wait_for_timeout(SETTLE_MS)
            html = await page.content()
            body_text = await page.evaluate(_BODY_TEXT_SCRIPT)
        finally:
            await browser.close()
    return html, body_text


async def _fetch_url_to_markdown_unbounded(url: str) -> str:
    html, body_text = await _load_page(url)
    return cap_jd_text(extract_markdown(html, body_text, url), url)


async def fetch_url_to_markdown(url: str) -> str:
    """Fetch a URL and return its job description as capped markdown."""
    return await asyncio.wait_for(
        _fetch_url_to_markdown_unbounded(url),
        timeout=_outer_timeout_s(),
    )
```

- [ ] **Step 5: Run the tests to verify they pass**

Run: `uv run pytest tests/test_jd_fetcher.py tests/test_jd_fetch_node.py -q`
Expected: all pass. If `test_extract_markdown_uses_trafilatura_on_rich_page` fails because trafilatura returns less than 1,200 characters for `_ARTICLE`, make the paragraphs in the test fixture longer (more repetitions), not the threshold smaller. If trafilatura strips the `<h1>` title, that is acceptable only if the title appears elsewhere in the extract; otherwise report as DONE_WITH_CONCERNS with the actual output pasted in your report.

- [ ] **Step 6: Full suite, lint, types**

```bash
uv run ruff check . && uv run ruff format --check . && uv run pyright && uv run pytest -q
```
Expected: clean, 0 errors, all tests pass (count goes from 658 to 658 − 5 old fetcher tests + 11 new).

- [ ] **Step 7: Measure the import-time change and record it**

```bash
uv run python -X importtime -c "import callback.server" 2>&1 | grep -E "\|\s+(callback\.server|callback\.jd_fetcher)\s*$"
```
Record the cumulative microseconds for `callback.server` and `callback.jd_fetcher` in your report. The pre-change numbers on this machine (warm cache) were `callback.server` ≈ 1,422,620 µs and `callback.jd_fetcher` ≈ 396,011 µs (of which crawl4ai ≈ 395,690 µs).

- [ ] **Step 8: Commit**

```bash
git add pyproject.toml uv.lock callback/jd_fetcher.py tests/test_jd_fetcher.py
git commit -m "feat(fetch): replace crawl4ai with Playwright + trafilatura

Chrome user agent, 1280x900 viewport, domcontentloaded plus a 2.5 s
settle. trafilatura (lazy import) extracts markdown; a thin extraction
falls back to body text. jd_text is capped at 16,000 characters
(~4,000 tokens) with a fetch_oversized log. CALLBACK_FETCH_MAGIC and
CALLBACK_FETCH_WAIT_UNTIL are gone.

Co-Authored-By: Claude Fable 5.1 <noreply@anthropic.com>
Claude-Session: https://claude.ai/code/session_01CBmQfLDXe6dxY5JVQnvHcz"
```

---

### Task 2: E1 fetch fixtures for the five measured URLs

**Files:**
- Create: `evals/__init__.py` (empty)
- Create: `evals/extract/qualcomm.md`, `evals/extract/apple.md`, `evals/extract/ashby.md`, `evals/extract/cedar.md`, `evals/extract/greenhouse.md`
- Create: `evals/extract/qualcomm.golden.json`, `apple.golden.json`, `ashby.golden.json`, `cedar.golden.json`, `greenhouse.golden.json`
- Create: `evals/extract/sources.json`
- Create: `evals/test_fetch_recall.py`
- Create: `scripts/build_fetch_fixtures.py`
- Modify: `pyproject.toml` (`testpaths = ["tests", "evals"]`), `.github/workflows/ci.yml` (two pytest lines), `.pre-commit-config.yaml` (pytest-unit entry)

**Interfaces:**
- Consumes: `callback.jd_fetcher.fetch_url_to_markdown` (Task 1), `callback.jd_fetcher.CHARS_PER_TOKEN`.
- Produces: `evals.test_fetch_recall.recall(text: str, golden: dict) -> dict` with shape `{"found": int, "total": int, "missing": list[str]}`; the fixture files consumed by M6's E1 later.

The five sources (archived application JSON under `~/.local/share/callback/applications/`, each with `jd_url` and `keywords`):

| board | archived session | jd_url |
|-------|------------------|--------|
| qualcomm | `934b4d18-a3cf-4c4a-b385-98f2658dcba5` | `https://careers.qualcomm.com/careers/job/446720282038?hl=en-US&utm_source=linkedin&domain=qualcomm.com&source=APPLICANT_SOURCE-6-2` |
| apple | `0ce0fbd3-8642-49b4-9e34-9c74eaf01c27` | `https://jobs.apple.com/en-us/details/200670706/software-engineer-universal-media` |
| ashby | `44d1011d-aeb2-48df-8caa-d47d712e2de7` | `https://jobs.ashbyhq.com/Deepgram/94ae2781-a85f-493a-86c1-ff85a9289355` |
| cedar | `1bdef50c-d41f-4189-9b71-0ed76754db0a` | `https://careers.cedar.build/38511` |
| greenhouse | `00ad1551-849c-4cbe-8078-68c94290a517` | `https://job-boards.greenhouse.io/hightouch/jobs/5983811004` |

All five returned HTTP 200 with real page bodies on 2026-09-04 (probed with the Task 1 user agent).

- [ ] **Step 1: Write the fixture builder script**

`scripts/build_fetch_fixtures.py`:

```python
#!/usr/bin/env python3
"""Build (or refresh) the E1 fetch fixtures under evals/extract/.

For each entry in evals/extract/sources.json: fetch the URL with the production
fetcher, write <board>.md, copy the archived keywords to <board>.golden.json,
and record the recall of the golden terms against the fetched text back into
sources.json so the CI test can assert it byte-for-byte.

Usage: uv run python scripts/build_fetch_fixtures.py [board ...]
"""

from __future__ import annotations

import asyncio
import json
import sys
from datetime import UTC, datetime
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from callback.jd_fetcher import CHARS_PER_TOKEN, fetch_url_to_markdown  # noqa: E402
from evals.test_fetch_recall import recall  # noqa: E402

EXTRACT_DIR = Path(__file__).resolve().parent.parent / "evals" / "extract"
APPS_DIR = Path.home() / ".local" / "share" / "callback" / "applications"


def _archived_keywords(session_id: str) -> dict:
    return json.loads((APPS_DIR / f"{session_id}.json").read_text())["keywords"]


def build(board: str, source: dict) -> dict:
    markdown = asyncio.run(fetch_url_to_markdown(source["jd_url"]))
    golden = _archived_keywords(source["archived_session"])
    (EXTRACT_DIR / f"{board}.md").write_text(markdown, encoding="utf-8")
    (EXTRACT_DIR / f"{board}.golden.json").write_text(
        json.dumps(golden, indent=2, ensure_ascii=False) + "\n", encoding="utf-8"
    )
    return {
        **source,
        "fetched_at": datetime.now(UTC).isoformat(timespec="seconds"),
        "fetched_chars": len(markdown),
        "fetched_tokens_est": len(markdown) // CHARS_PER_TOKEN,
        "recall": recall(markdown, golden),
    }


def main(argv: list[str]) -> int:
    sources_path = EXTRACT_DIR / "sources.json"
    sources = json.loads(sources_path.read_text())
    boards = argv or sorted(sources)
    for board in boards:
        sources[board] = build(board, sources[board])
        r = sources[board]["recall"]
        print(f"{board:11s} {r['found']}/{r['total']} found, missing={r['missing']}")
    sources_path.write_text(
        json.dumps(sources, indent=2, ensure_ascii=False) + "\n", encoding="utf-8"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
```

- [ ] **Step 2: Seed `evals/extract/sources.json`**

```json
{
  "qualcomm": {
    "jd_url": "https://careers.qualcomm.com/careers/job/446720282038?hl=en-US&utm_source=linkedin&domain=qualcomm.com&source=APPLICANT_SOURCE-6-2",
    "archived_session": "934b4d18-a3cf-4c4a-b385-98f2658dcba5"
  },
  "apple": {
    "jd_url": "https://jobs.apple.com/en-us/details/200670706/software-engineer-universal-media",
    "archived_session": "0ce0fbd3-8642-49b4-9e34-9c74eaf01c27"
  },
  "ashby": {
    "jd_url": "https://jobs.ashbyhq.com/Deepgram/94ae2781-a85f-493a-86c1-ff85a9289355",
    "archived_session": "44d1011d-aeb2-48df-8caa-d47d712e2de7"
  },
  "cedar": {
    "jd_url": "https://careers.cedar.build/38511",
    "archived_session": "1bdef50c-d41f-4189-9b71-0ed76754db0a"
  },
  "greenhouse": {
    "jd_url": "https://job-boards.greenhouse.io/hightouch/jobs/5983811004",
    "archived_session": "00ad1551-849c-4cbe-8078-68c94290a517"
  }
}
```

- [ ] **Step 3: Write the recall test module (failing first)**

`evals/__init__.py`: empty file.

`evals/test_fetch_recall.py`:

```python
"""E1 fetch fixtures: does the fetcher return text that still contains the keywords?

The CI test reads the committed fixtures and asserts the recall recorded in
sources.json byte-for-byte, so a fixture refresh that loses terms is visible in
the diff. The `local` test re-fetches each URL live and must land within one
term of the recorded recall.
"""

from __future__ import annotations

import asyncio
import json
from pathlib import Path

import pytest

EXTRACT_DIR = Path(__file__).resolve().parent / "extract"
SOURCES = json.loads((EXTRACT_DIR / "sources.json").read_text())
LIVE_RECALL_TOLERANCE = 1


def golden_terms(golden: dict) -> list[str]:
    """Every keyword the host extracted: required, preferred, and each OR-group member."""
    terms: list[str] = list(golden.get("required", [])) + list(golden.get("preferred", []))
    for group in golden.get("required_any", []) + golden.get("preferred_any", []):
        terms.extend(group)
    return sorted(set(terms))


def recall(text: str, golden: dict) -> dict:
    haystack = text.lower()
    terms = golden_terms(golden)
    missing = [t for t in terms if t.lower() not in haystack]
    return {"found": len(terms) - len(missing), "total": len(terms), "missing": missing}


@pytest.mark.parametrize("board", sorted(SOURCES))
def test_fixture_recall_matches_recorded(board):
    text = (EXTRACT_DIR / f"{board}.md").read_text(encoding="utf-8")
    golden = json.loads((EXTRACT_DIR / f"{board}.golden.json").read_text())

    actual = recall(text, golden)
    expected = SOURCES[board]["recall"]
    assert actual == expected


@pytest.mark.local
@pytest.mark.parametrize("board", sorted(SOURCES))
def test_live_fetch_recall_within_tolerance(board):
    from callback.jd_fetcher import fetch_url_to_markdown

    golden = json.loads((EXTRACT_DIR / f"{board}.golden.json").read_text())
    text = asyncio.run(fetch_url_to_markdown(SOURCES[board]["jd_url"]))

    live = recall(text, golden)
    recorded = SOURCES[board]["recall"]
    actual = {"within_tolerance": live["found"] >= recorded["found"] - LIVE_RECALL_TOLERANCE}
    expected = {"within_tolerance": True}
    assert actual == expected, f"live={live} recorded={recorded}"
```

Run: `uv run pytest evals/ -q`
Expected: FAIL — the `.md` and `.golden.json` files do not exist yet and `sources.json` has no `recall` key.

- [ ] **Step 4: Build the fixtures**

```bash
uv run python scripts/build_fetch_fixtures.py
```
Expected: five lines like `qualcomm    17/19 found, missing=[...]`. Paste all five lines in your report, together with `fetched_tokens_est` per board from `sources.json`. If any board's recall is more than 2 terms below `total`, look at the `.md` and report what is missing and why (a login wall, a truncated page, a term the host paraphrased) as a concern; do not edit the golden to make it pass.

Then check the fixture sizes: every `.md` must be at most 16,000 characters (the cap) — `wc -c evals/extract/*.md`.

- [ ] **Step 5: Run the tests to verify they pass**

```bash
uv run pytest evals/ -q                # CI half
uv run pytest evals/ -m local -q       # live half (needs network; ~20 s)
```
Expected: 5 passed; 5 passed.

- [ ] **Step 6: Make CI and pre-push run `evals/`**

`pyproject.toml`: `testpaths = ["tests", "evals"]`.

`.github/workflows/ci.yml`: change both pytest lines to drop the explicit `tests/` path so `testpaths` applies:
- `uv run pytest -m "not integration and not local" --tb=short`
- `uv run pytest -m integration --tb=short`

`.pre-commit-config.yaml`, hook `pytest-unit`: `entry: uv run pytest -m "not integration and not local" --tb=short -q`.

Run: `uv run pytest -m "not integration and not local" -q` — expected: full suite plus the five fixture tests pass.

- [ ] **Step 7: Lint, types, commit**

```bash
uv run ruff check . && uv run ruff format --check . && uv run pyright
git add evals scripts/build_fetch_fixtures.py pyproject.toml .github/workflows/ci.yml .pre-commit-config.yaml
git commit -m "test(evals): E1 fetch fixtures for the five measured job boards

Each fixture is the production fetcher's markdown for a live URL plus the
keywords archived when that job was applied to. CI asserts the recorded
recall against the committed fixture; the local test re-fetches live.

Co-Authored-By: Claude Fable 5.1 <noreply@anthropic.com>
Claude-Session: https://claude.ai/code/session_01CBmQfLDXe6dxY5JVQnvHcz"
```

---

### Task 3: `smoke_apply.py` can run against a live URL

**Files:**
- Modify: `scripts/smoke_apply.py`

**Interfaces:**
- Consumes: `callback.server.load_jd(jd_url=..., resume_label=...)` (existing), `callback.jd_fetcher.MIN_MARKDOWN_CHARS`.

- [ ] **Step 1: Add the optional URL argument**

At the top of `main()` in `scripts/smoke_apply.py`, accept `sys.argv[1]` as an optional URL. Replace the Phase 1 block:

```python
    jd_url = sys.argv[1] if len(sys.argv) > 1 else None
    ...
        # Phase 1: load_jd
        if jd_url:
            load_result = load_jd(jd_url=jd_url, resume_label=resume_label)
        else:
            load_result = load_jd(jd_raw_text=jd_text, resume_label=resume_label)
        loaded = json.loads(load_result)
        session_id = loaded["session_id"]
        assert loaded["status"] == "ok", f"load_jd failed: {loaded}"
        assert loaded["next_action"] == "extract_keywords", f"unexpected: {loaded}"
        assert loaded["data"]["extraction_protocol"] == EXTRACTION_PROTOCOL
        loaded_text = loaded["data"]["jd_text"]
        if jd_url:
            assert len(loaded_text) > MIN_MARKDOWN_CHARS, f"fetched JD too short: {loaded_text!r}"
            print(f"fetched {len(loaded_text)} chars from {jd_url}")
        else:
            assert loaded_text == jd_text, f"jd_text mismatch: {loaded_text!r}"
```

Add `from callback.jd_fetcher import MIN_MARKDOWN_CHARS` to the imports. Keep the rest of the script unchanged. Update the module docstring: `"""Smoke test for the apply MCP handoff tools. Pass a job URL as the first argument to exercise the fetcher."""`.

- [ ] **Step 2: Run it three ways**

```bash
uv run python scripts/smoke_apply.py                                                   # raw text path
uv run python scripts/smoke_apply.py https://careers.cedar.build/38511
uv run python scripts/smoke_apply.py https://job-boards.greenhouse.io/hightouch/jobs/5983811004
uv run python scripts/smoke_apply.py https://jobs.ashbyhq.com/Deepgram/94ae2781-a85f-493a-86c1-ff85a9289355
```
Expected: each ends with `SMOKE OK`. Paste the `fetched N chars` line and the final line of each run in your report. A run that fails is a finding, not something to work around.

- [ ] **Step 3: Lint and commit**

```bash
uv run ruff check scripts && uv run ruff format --check scripts
git add scripts/smoke_apply.py
git commit -m "chore(smoke): smoke_apply.py accepts a job URL to exercise the fetcher

Co-Authored-By: Claude Fable 5.1 <noreply@anthropic.com>
Claude-Session: https://claude.ai/code/session_01CBmQfLDXe6dxY5JVQnvHcz"
```

---

### Task 4: Docs — env vars, fetcher description, INTENT bookkeeping

**Files:**
- Modify: `CLAUDE.md` (Commands comment on line 31, Env Vars lines 66–69)
- Modify: `AGENTS.md` (lines 72–75 and 199–202, plus any "Crawl4AI" mention)
- Modify: `INTENT.md` (W1 row, M3 heading)

- [ ] **Step 1: `CLAUDE.md`**

Replace the four `CALLBACK_FETCH_*` bullets with:

```
- `CALLBACK_FETCH_PAGE_TIMEOUT_MS`: Override the Playwright page-load timeout in milliseconds. Default: `30000`.
- `CALLBACK_FETCH_OUTER_TIMEOUT_S`: Override the outer fetch timeout in seconds. Default: `35`.
```

Change the comment `# One-time browser setup for Crawl4AI job-description fetching` to `# One-time browser setup (job-description fetching and PDF rendering)`.

Under "Apply graph", after the error-routing sentence, add one sentence: `jd_fetch` loads the page with Playwright (Chrome user agent, `domcontentloaded` plus a 2.5 s settle), extracts markdown with trafilatura, falls back to body text when the extraction is thin, and caps `jd_text` at 16,000 characters (about 4,000 tokens), logging `fetch_oversized`.

- [ ] **Step 2: `AGENTS.md`**

Same two-bullet replacement in both places (`grep -n "CALLBACK_FETCH" AGENTS.md` to find them). Replace every "Crawl4AI" with "Playwright". Confirm with `grep -in "crawl4ai\|FETCH_MAGIC\|FETCH_WAIT" CLAUDE.md AGENTS.md README.md` → no output.

- [ ] **Step 3: `INTENT.md`**

- W1 row: replace the last cell with `Fixed (M3)`.
- Under `### M3 — Replace the fetcher`, insert as the first line after the heading: `Shipped 2026-09-04: W1.` followed by a one-line measurement: `Measured after the swap: server import ≈ <N> ms (was ≈ 1,420 ms warm); <K> runtime packages (was 148). Fixtures: evals/extract/.` — fill `<N>` and `<K>` from the Task 1 report (the controller passes them in the dispatch).

- [ ] **Step 4: Commit**

```bash
git add CLAUDE.md AGENTS.md INTENT.md
git commit -m "docs: Playwright + trafilatura fetcher, drop crawl4ai env vars, mark W1 fixed (M3)

Co-Authored-By: Claude Fable 5.1 <noreply@anthropic.com>
Claude-Session: https://claude.ai/code/session_01CBmQfLDXe6dxY5JVQnvHcz"
```

---

## Self-review notes

- Spec coverage: item 1 (UA, viewport) → Task 1 `_load_page`; item 2 (wait strategy) → Task 1; item 3 (trafilatura call, lazy import, 300-token fallback) → Task 1 `extract_markdown` / `_trafilatura_markdown`; item 4 (4,000-token cap + `fetch_oversized`) → Task 1 `cap_jd_text`; item 5 (crawl4ai and its env vars removed; page/outer timeouts kept) → Task 1 Step 1 and Task 4. "Done when": crawl4ai out of `pyproject.toml` (Task 1); five URLs as E1 fixtures with archived keywords as golden (Task 2); `smoke_apply.py` on three (Task 3); import-time drop measured (Task 1 Step 7, recorded in Task 4).
- Type consistency: `extract_markdown(html, body_text, url)` and `cap_jd_text(text, url)` are used with those exact parameter orders in Task 1 tests and `_fetch_url_to_markdown_unbounded`; `recall(text, golden)` is defined in Task 2's test module and imported by the builder script.
- The thin-extraction fallback is narrower than the spec sentence ("fall back to the page's body text"): it falls back only when the body text is longer than the extraction, so a genuinely tiny page keeps its extraction instead of being replaced by even less. Recorded as a ruling in the ledger.
