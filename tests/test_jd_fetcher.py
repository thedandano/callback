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
    extracted = jd_fetcher._trafilatura_markdown(_ARTICLE)

    markdown = jd_fetcher.extract_markdown(extracted, "body text", "https://example.com/job")

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
    extracted = jd_fetcher._trafilatura_markdown("<html><body><p>Apply now.</p></body></html>")
    body_text = "Senior Python Engineer\n" + ("Build APIs and ship reliable systems. " * 60)

    markdown = jd_fetcher.extract_markdown(extracted, body_text, "https://example.com/job")

    actual = {"markdown": markdown, "events": _events(caplog)}
    expected = {
        "markdown": body_text,
        "events": [
            {
                "event": "fetch_thin_extraction",
                "url": "https://example.com/job",
                "extracted_chars": len(extracted),
                "body_chars": len(body_text),
            }
        ],
    }
    assert actual == expected


def test_extract_markdown_rejects_shell_page_with_short_body(caplog):
    """A login wall or empty SPA shell: thin extraction AND a short body. The body
    must not be promoted to a JD just because it is longer than the extraction."""
    caplog.set_level("INFO", logger="callback.jd_fetcher")
    body_text = "Please sign in to view this job posting. Cookies are required."

    with pytest.raises(RuntimeError) as exc_info:
        jd_fetcher.extract_markdown("", body_text, "https://example.com/job")

    actual = {"message": str(exc_info.value), "events": _events(caplog)}
    expected = {
        "message": f"thin page: 0 chars, under the {jd_fetcher.MIN_EXTRACT_CHARS} minimum",
        "events": [
            {
                "event": "fetch_thin",
                "url": "https://example.com/job",
                "extracted_chars": 0,
                "body_chars": len(body_text),
                "min_chars": jd_fetcher.MIN_EXTRACT_CHARS,
            }
        ],
    }
    assert actual == expected


def test_extract_markdown_rejects_thin_extraction_when_body_is_shorter(caplog):
    caplog.set_level("INFO", logger="callback.jd_fetcher")
    extracted = "Apply now for this role."

    with pytest.raises(RuntimeError):
        jd_fetcher.extract_markdown(extracted, "x", "https://example.com/job")

    assert [e["event"] for e in _events(caplog)] == ["fetch_thin"]


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
                "kept_chars": jd_fetcher.MAX_JD_CHARS,
            }
        ],
    }
    assert actual == expected


def test_cap_jd_text_cuts_at_last_newline(caplog):
    caplog.set_level("INFO", logger="callback.jd_fetcher")
    text = "a" * 15_990 + "\n" + "b" * 100

    capped = jd_fetcher.cap_jd_text(text, "https://example.com/job")

    actual = {"chars": len(capped), "events": _events(caplog)}
    expected = {
        "chars": 15_990,
        "events": [
            {
                "event": "fetch_oversized",
                "url": "https://example.com/job",
                "original_chars": len(text),
                "cap_chars": jd_fetcher.MAX_JD_CHARS,
                "kept_chars": 15_990,
            }
        ],
    }
    assert actual == expected


def test_cap_jd_text_ignores_a_newline_far_from_the_cap(caplog):
    """A title line followed by one long paragraph must not collapse to the title."""
    caplog.set_level("INFO", logger="callback.jd_fetcher")
    text = "# Title\n" + "x" * (jd_fetcher.MAX_JD_CHARS + 500)

    capped = jd_fetcher.cap_jd_text(text, "https://example.com/job")

    actual = {"chars": len(capped), "kept": _events(caplog)[0]["kept_chars"]}
    expected = {"chars": jd_fetcher.MAX_JD_CHARS, "kept": jd_fetcher.MAX_JD_CHARS}
    assert actual == expected


def test_cap_jd_text_passes_short_text_unchanged(caplog):
    caplog.set_level("INFO", logger="callback.jd_fetcher")

    capped = jd_fetcher.cap_jd_text("short", "https://example.com/job")

    actual = {"text": capped, "events": _events(caplog)}
    expected = {"text": "short", "events": []}
    assert actual == expected


# --- _with_title -------------------------------------------------------------


_BODY = "Body text about the role: build APIs, ship reliable systems, mentor the team."


def test_with_title_prepends_when_missing():
    markdown = jd_fetcher._with_title(_BODY, "Senior Engineer | Acme")

    assert markdown == f"# Senior Engineer | Acme\n\n{_BODY}"


def test_with_title_skips_when_present():
    markdown = jd_fetcher._with_title(
        "# SENIOR ENGINEER | ACME\n\nBody text.", "Senior Engineer | Acme"
    )

    assert markdown == "# SENIOR ENGINEER | ACME\n\nBody text."


def test_with_title_strips_leading_hashes():
    """Qualcomm's <title> is literally '#Software Engineer ...'."""
    markdown = jd_fetcher._with_title(_BODY, "#Software Engineer - Edge AI | Qualcomm")

    assert markdown == f"# Software Engineer - Edge AI | Qualcomm\n\n{_BODY}"


def test_with_title_leaves_thin_content_alone():
    """An empty SPA shell with a long <title> must still fail jd_fetch's empty check."""
    markdown = jd_fetcher._with_title("", "Careers at ExampleCo | Software Engineer, Platform")

    assert markdown == ""


def test_with_title_skips_blank():
    markdown = jd_fetcher._with_title("Body text about the role.", "   ")

    assert markdown == "Body text about the role."


# --- fetch_url_to_markdown (Playwright wiring, browser faked) ----------------


class _FakeResponse:
    def __init__(self, status: int):
        self.status = status


class _FakePage:
    def __init__(
        self,
        calls: dict,
        html: str,
        body_text: str,
        goto_error=None,
        goto_delay=0.0,
        status: int | None = 200,
        title: str = "",
    ):
        self._calls = calls
        self._html = html
        self._body_text = body_text
        self._goto_error = goto_error
        self._goto_delay = goto_delay
        self._status = status
        self._title = title

    async def goto(self, url, **kwargs):
        self._calls["goto"] = {"url": url, **kwargs}
        if self._goto_delay:
            await asyncio.sleep(self._goto_delay)
        if self._goto_error:
            raise self._goto_error
        return _FakeResponse(self._status) if self._status is not None else None

    async def wait_for_timeout(self, ms):
        self._calls["settle_ms"] = ms

    async def content(self):
        return self._html

    async def evaluate(self, script):
        self._calls["evaluate"] = script
        return self._body_text

    async def title(self):
        return self._title


def _fake_playwright(
    monkeypatch, html="<html></html>", body_text="", close_delay=0.0, stop_delay=0.0, **page_kwargs
) -> dict:
    """Install a fake async_playwright; return the dict of recorded calls.

    The extraction subprocess is stubbed too (``run_killable`` returns the page
    html unchanged) so these wiring tests never spawn a child process; the
    subprocess itself is covered by the ``run_killable`` tests below.
    """
    calls: dict = {}
    page = _FakePage(calls, html, body_text, **page_kwargs)

    async def _close():
        if close_delay:
            await asyncio.sleep(close_delay)
        calls["closed"] = True

    context = Mock()
    context.new_page = AsyncMock(return_value=page)
    browser = Mock()
    browser.new_context = AsyncMock(
        side_effect=lambda **kw: calls.__setitem__("new_context", kw) or context
    )
    browser.close = _close
    chromium = Mock()
    chromium.launch = AsyncMock(side_effect=lambda **kw: calls.__setitem__("launch", kw) or browser)
    playwright = Mock(chromium=chromium)

    async def _stop():
        if stop_delay:
            await asyncio.sleep(stop_delay)
        calls["stopped"] = True

    playwright.stop = _stop

    manager = Mock()
    manager.start = AsyncMock(return_value=playwright)
    monkeypatch.setattr(jd_fetcher, "async_playwright", lambda: manager)
    monkeypatch.setattr(jd_fetcher, "run_killable", lambda worker, arg, timeout: f"raw({arg})")
    return calls


def test_fetch_url_to_markdown_wires_playwright_and_extracts(monkeypatch):
    monkeypatch.delenv("CALLBACK_FETCH_PAGE_TIMEOUT_MS", raising=False)
    monkeypatch.delenv("CALLBACK_FETCH_OUTER_TIMEOUT_S", raising=False)
    calls = _fake_playwright(
        monkeypatch, html="<html>page</html>", body_text="body", title="Job Title | Board"
    )
    monkeypatch.setattr(
        jd_fetcher,
        "extract_markdown",
        lambda extracted, body_text, url: f"md({extracted},{body_text},{url}) " + "filler " * 10,
    )

    markdown = asyncio.run(jd_fetcher.fetch_url_to_markdown("https://example.com/job"))

    actual = {"markdown": markdown, **calls}
    expected = {
        "markdown": "# Job Title | Board\n\n"
        + "md(raw(<html>page</html>),body,https://example.com/job) "
        + "filler " * 10,
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
        "stopped": True,
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


def test_fetch_url_to_markdown_raises_on_http_error(monkeypatch, caplog):
    caplog.set_level("INFO", logger="callback.jd_fetcher")
    calls = _fake_playwright(monkeypatch, status=404)

    with pytest.raises(RuntimeError) as exc_info:
        asyncio.run(jd_fetcher.fetch_url_to_markdown("https://example.com/job"))

    actual = {
        "message": str(exc_info.value),
        "closed": calls.get("closed"),
        "events": _events(caplog),
    }
    expected = {
        "message": "http status 404",
        "closed": True,
        "events": [{"event": "fetch_status", "url": "https://example.com/job", "status": 404}],
    }
    assert actual == expected


def test_fetch_url_to_markdown_raises_on_unfollowed_redirect(monkeypatch, caplog):
    caplog.set_level("INFO", logger="callback.jd_fetcher")
    calls = _fake_playwright(monkeypatch, status=302)

    with pytest.raises(RuntimeError) as exc_info:
        asyncio.run(jd_fetcher.fetch_url_to_markdown("https://example.com/job"))

    actual = {"message": str(exc_info.value), "closed": calls.get("closed")}
    expected = {"message": "http status 302", "closed": True}
    assert actual == expected


def test_fetch_url_to_markdown_raises_when_goto_returns_none(monkeypatch, caplog):
    caplog.set_level("INFO", logger="callback.jd_fetcher")
    calls = _fake_playwright(monkeypatch, status=None)

    with pytest.raises(RuntimeError) as exc_info:
        asyncio.run(jd_fetcher.fetch_url_to_markdown("https://example.com/job"))

    actual = {
        "message": str(exc_info.value),
        "closed": calls.get("closed"),
        "events": _events(caplog),
    }
    expected = {
        "message": "http status None",
        "closed": True,
        "events": [{"event": "fetch_status", "url": "https://example.com/job", "status": None}],
    }
    assert actual == expected


def test_fetch_url_to_markdown_propagates_outer_timeout(monkeypatch):
    monkeypatch.setattr(jd_fetcher, "_outer_timeout_s", lambda: 0.01)
    _fake_playwright(monkeypatch, goto_delay=1.0)

    with pytest.raises(asyncio.TimeoutError):
        asyncio.run(jd_fetcher.fetch_url_to_markdown("https://example.com/job"))


def test_fetch_gives_extraction_only_the_remaining_budget(monkeypatch):
    """The outer timeout bounds the whole fetch: the killable extraction gets what is
    left after the page load, not a fresh budget."""
    monkeypatch.setattr(jd_fetcher, "_outer_timeout_s", lambda: 2.0)
    _fake_playwright(monkeypatch, goto_delay=0.5)
    seen: dict = {}

    def capture(worker, arg, timeout):
        seen["timeout"] = timeout
        return "x" * 2_000

    monkeypatch.setattr(jd_fetcher, "run_killable", capture)

    asyncio.run(jd_fetcher.fetch_url_to_markdown("https://example.com/job"))

    actual = {"budget_reduced": 1.0 < seen["timeout"] < 1.6}
    expected = {"budget_reduced": True}
    assert actual == expected


def test_fetch_url_to_markdown_bounds_a_hung_browser_close(monkeypatch, caplog):
    """A browser that ignores close() must not hold the fetch past CLOSE_TIMEOUT_S."""
    import time

    caplog.set_level("INFO", logger="callback.jd_fetcher")
    monkeypatch.setattr(jd_fetcher, "CLOSE_TIMEOUT_S", 0.05)
    _fake_playwright(monkeypatch, close_delay=5.0)
    monkeypatch.setattr(jd_fetcher, "extract_markdown", lambda *_: "y" * 2_000)

    start = time.perf_counter()
    asyncio.run(jd_fetcher.fetch_url_to_markdown("https://example.com/job"))
    elapsed = time.perf_counter() - start

    cleanup_events = [e for e in _events(caplog) if e["event"] == "browser_cleanup_failed"]
    actual = {"prompt": elapsed < 1.0, "events": cleanup_events}
    expected = {
        "prompt": True,
        "events": [
            {
                "event": "browser_cleanup_failed",
                "url": "https://example.com/job",
                "step": "browser.close",
                "error_class": "TimeoutError",
            }
        ],
    }
    assert actual == expected


def test_outer_timeout_during_browser_close_still_stops_the_driver(monkeypatch, caplog):
    """The outer deadline landing mid-close must not skip playwright.stop()."""
    import time

    caplog.set_level("INFO", logger="callback.jd_fetcher")
    monkeypatch.setattr(jd_fetcher, "_outer_timeout_s", lambda: 0.2)
    monkeypatch.setattr(jd_fetcher, "CLOSE_TIMEOUT_S", 10.0)
    calls = _fake_playwright(monkeypatch, close_delay=5.0)

    start = time.perf_counter()
    with pytest.raises(asyncio.TimeoutError):
        asyncio.run(jd_fetcher.fetch_url_to_markdown("https://example.com/job"))
    elapsed = time.perf_counter() - start

    events = [e for e in _events(caplog) if e["event"].startswith("browser_cleanup")]
    actual = {"stopped": calls.get("stopped"), "prompt": elapsed < 1.0, "events": events}
    expected = {
        "stopped": True,
        "prompt": True,
        "events": [
            {
                "event": "browser_cleanup_cancelled",
                "url": "https://example.com/job",
                "step": "browser.close",
            }
        ],
    }
    assert actual == expected


def test_cleanup_after_the_deadline_gets_only_the_grace_bound(monkeypatch, caplog):
    """Once the outer deadline has fired, a slow playwright.stop() is cut at the
    grace bound instead of a fresh CLOSE_TIMEOUT_S, so the overrun stays small."""
    import time

    caplog.set_level("INFO", logger="callback.jd_fetcher")
    monkeypatch.setattr(jd_fetcher, "_outer_timeout_s", lambda: 0.2)
    monkeypatch.setattr(jd_fetcher, "CLOSE_TIMEOUT_S", 10.0)
    monkeypatch.setattr(jd_fetcher, "CANCELLED_CLEANUP_GRACE_S", 0.1)
    calls = _fake_playwright(monkeypatch, close_delay=5.0, stop_delay=5.0)

    start = time.perf_counter()
    with pytest.raises(asyncio.TimeoutError):
        asyncio.run(jd_fetcher.fetch_url_to_markdown("https://example.com/job"))
    elapsed = time.perf_counter() - start

    events = [e for e in _events(caplog) if e["event"].startswith("browser_cleanup")]
    actual = {"stopped": calls.get("stopped"), "overrun_small": elapsed < 1.0, "events": events}
    expected = {
        "stopped": None,
        "overrun_small": True,
        "events": [
            {
                "event": "browser_cleanup_cancelled",
                "url": "https://example.com/job",
                "step": "browser.close",
            },
            {
                "event": "browser_cleanup_failed",
                "url": "https://example.com/job",
                "step": "playwright.stop",
                "error_class": "TimeoutError",
            },
        ],
    }
    assert actual == expected


# --- run_killable (real spawned child processes) ------------------------------


def _echo_worker(conn, text):
    conn.send(("ok", text))
    conn.close()


def _sleep_worker(conn, seconds):
    import time

    time.sleep(seconds)
    conn.send(("ok", "late"))
    conn.close()


def _boom_worker(conn, _):
    raise ValueError("boom")


def test_run_killable_returns_worker_result():
    assert jd_fetcher.run_killable(_echo_worker, "hello", 30.0) == "hello"


def test_run_killable_kills_slow_worker():
    import time

    start = time.perf_counter()
    with pytest.raises(TimeoutError) as exc_info:
        jd_fetcher.run_killable(_sleep_worker, 30.0, 0.3)
    elapsed = time.perf_counter() - start

    actual = {"message": str(exc_info.value), "bounded": elapsed < 3.0}
    expected = {"message": "extraction exceeded 0.3s; worker killed", "bounded": True}
    assert actual == expected


def test_run_killable_surfaces_worker_crash():
    with pytest.raises(RuntimeError) as exc_info:
        jd_fetcher.run_killable(_boom_worker, None, 30.0)

    assert str(exc_info.value) == "extraction worker exited without a result"


def test_extract_worker_runs_trafilatura_in_child():
    markdown = jd_fetcher.run_killable(jd_fetcher._extract_worker, _ARTICLE, 60.0)

    actual = {"has_title": "Senior Python Engineer" in markdown, "long": len(markdown) > 1_000}
    expected = {"has_title": True, "long": True}
    assert actual == expected


# --- import cost -------------------------------------------------------------


def test_importing_jd_fetcher_does_not_import_trafilatura():
    """trafilatura is imported lazily inside the fetch so server start-up does not pay for it."""
    code = "import sys, callback.jd_fetcher; print('trafilatura' in sys.modules)"
    out = subprocess.run(
        [sys.executable, "-c", code], capture_output=True, text=True, check=True
    ).stdout.strip()
    assert out == "False"
