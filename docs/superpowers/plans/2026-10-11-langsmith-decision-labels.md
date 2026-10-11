# LangSmith Decision Labels Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development to implement this plan task-by-task (the owner chose subagents). Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Make LangSmith show which path the code took (where the job text came from, whether it looked cut off, which resume text was scored, retries), and make the tracing docs say what the code really sends.

**Architecture:** One helper, `record_decision(key, value)`, in `callback/observability.py`, stamps a short fixed label onto the metadata of the LangSmith span that is open at that moment. Call sites sit next to each decision (next to the existing log line where there is one). Labels are booleans or lowercase tokens, so they can never carry job, resume, or story text. No new module, no state fields, no return-shape changes, no new settings.

**Tech Stack:** Python 3.12, LangGraph, `langsmith` 0.8.0 (`run_helpers.get_current_run_tree`), pytest, ruff, pyright.

**Spec:** none on disk. The requirements are the Context section below. Decisions made by the owner in the planning conversation (2026-10-10/11): "Option 1" (labels, plus rewrite the docs to match the code); 9 labels now, the rest noted as a follow-up; open an issue for telling the model about a cut-off posting; branch from latest `main`; subagents execute.

## Context

On 2026-10-10 a LinkedIn posting (Lyra Health) was fetched as 2,691 bytes with a `fetch_truncated` warning, still ended in `fetch_ok`, and nothing told the model or LangSmith. The warning lived only in `~/.local/state/callback/server.log`. An audit found the same shape elsewhere: the code makes a choice, logs it, and the trace shows nothing.

The audit also found that the docs are wrong. `CLAUDE.md`, `AGENTS.md` and `README.md` say traces never include posting text, edits, or file paths. In fact tool spans send most tool arguments and the whole reply; only node spans are cut down to lengths and key names. The owner is fine with what tool spans send. The fix is to state it honestly, not to change it.

**Verified before planning** (in-memory runs with real `langsmith.traceable` and a mocked HTTP session; repeated by an independent Opus review):

- A label set inside a node, inside `asyncio.run(...)`, and inside `asyncio.to_thread(...)` lands on that **node's** span, and the span-close PATCH carries it (`extra.metadata`).
- A label set in a tool body lands on the **tool** span, and every node span created afterwards inherits it.
- From inside a node, `run_tree.parent_run` is `None`. Node labels cannot be copied up to the tool span. Do not try.
- `callback/jd_fetcher.py` may import `callback.observability`. The fetcher's spawned extraction child re-runs the server's own start-up imports, so it already loads `observability`, `langgraph` and `langsmith` on every fetch today. Under pytest and the eval runner the child is lighter today and will pay roughly 200–350 ms more, inside a 35-second budget. Accepted.

**Reviewed:** an Opus subagent ran a ponytail (over-engineering) audit and a general review on the first draft. This version applies its findings: 19 labels cut to 9, the separate stdlib module and sink removed, two stacked PRs cut to one, docs text corrected, live check rewritten, format check added.

## Global Constraints

- Branch `feat/trace-decision-labels` from `origin/main` at `10c01f8` or later. One PR, targeting `main`.
- Work in a git worktree under `.worktrees/` (already git-ignored; superpowers:using-git-worktrees). The owner's checkout has an unrelated modified `uv.lock` and untracked files; do not touch them.
- Imports go at the top of the file. Never inside a function.
- Tests compare whole objects: `assert actual == expected` with full dicts.
- Verify with all four, every task: `uv run pytest -q`, `uv run ruff check`, `uv run ruff format --check .`, `uv run pyright`. CI runs all of them. Ruff's rule set is `E, F, I, N, UP, B, SIM, C90`; line length is 100. If `ruff format --check` fails, run `uv run ruff format <the files you touched>` and re-run.
- Label keys and string values must match `[a-z0-9_]{1,48}`. Values may also be `True`/`False`. Never pass text that came from a posting, resume, story, URL, path, or exception message.
- `fetch_url_to_markdown(url) -> str` keeps its signature. `evals/test_fetch_recall.py` and `evals/runner.py` depend on it.
- Do not change what tool spans or node spans already send. Do not add settings. Do not touch `callback/scorer.py`, `callback/apply_graph.py`, `callback/profile_graph.py` or `callback/profile_nodes.py`.
- `_load_jd_impl` in `server.py` already carries `# noqa: C901`; do not add branches to it.
- Commit messages end with `Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>`. The PR description ends with `🤖 Generated with [Claude Code](https://claude.com/claude-code)`. Run PR and issue text through the `humanizer` skill.
- `$SCRATCH` in commands means the session scratchpad directory. Put PR and issue body drafts there, never in the repo and never in `/tmp`.
- Model per task: Sonnet (pattern-following code). One review at the end, before the PR is opened.

## Review Focus

1. **A label value built from content.** Someone later writes `record_decision("jd_source", state.jd_url)`. Expected: rejected, WARNING logged, nothing sent, and the warning does not echo the value. Pinned in Task 1 (`test_record_decision_rejects_anything_that_is_not_a_token`).
2. **No open span** (tracing off, the eval runner, unit tests calling the fetcher directly). Expected: silent no-op, never an exception. Pinned in Task 1 (`test_record_decision_does_nothing_without_an_open_span`).
3. **Label set inside the browser fetch's own event loop.** Expected: still reaches the `jd_fetch` span. Pinned in Task 1 (`tests/test_trace_decisions_wire.py`).
4. **Pasted text with no URL.** Today this path logs nothing. Expected: an INFO log line and `jd_source=pasted`. Pinned in Task 2.
5. **Fetch failed and there is no pasted text.** Expected: the error is raised as today and no `jd_source` label is written (there is no source). Pinned in Task 2 (`test_jd_fetch_failure_without_raw_text_writes_no_source_label`).

## File Structure

| File | Change | Responsibility |
|---|---|---|
| `callback/observability.py` | modify | add `record_decision` (the only place that touches the run tree for labels); correct two comments |
| `tests/conftest.py` | modify | add `decisions` fixture: a fake open span whose metadata dict the test reads |
| `tests/test_trace_decisions_wire.py` | create | one end-to-end check with real `langsmith.traceable` and a mocked HTTP session |
| `callback/apply_nodes.py` | modify | labels in `jd_fetch`, `parse_initial`, `_candidate_experience_years`, `score_initial`, `score_final` |
| `callback/jd_fetcher.py` | modify | labels for extraction fallback, cap, truncation |
| `callback/server.py` | modify | labels for resume pick and tailor retry |
| `AGENTS.md`, `CLAUDE.md`, `README.md` | modify | tracing sections rewritten to match the code; label table (in `AGENTS.md` only) |

## Label reference (the full set this plan adds)

Node-level labels appear on that node's span only. Tool-level labels appear on the tool span **and on every node span created after them** in the same tool call.

| Key | Values | Set in | Level |
|---|---|---|---|
| `jd_source` | `fetched`, `pasted`, `pasted_after_fetch_failed` | `apply_nodes.jd_fetch` | node (`jd_fetch`) |
| `jd_extraction` | `clean`, `body_text` | `jd_fetcher.extract_markdown` | node (`jd_fetch`) |
| `jd_capped` | bool | `jd_fetcher.cap_jd_text` | node (`jd_fetch`) |
| `jd_truncated` | bool | `jd_fetcher._fetch_url_to_markdown_unbounded` | node (`jd_fetch`) |
| `initial_score_source` | `resume_file`, `sections_text`, `none` | `apply_nodes.parse_initial` | node (`parse_initial`) |
| `experience_years` | `computed`, `partial`, `unavailable` | `apply_nodes._candidate_experience_years` | node (`parse_initial`, `tailor`) |
| `experience_evaluated` | bool | `apply_nodes.score_initial`, `score_final` | node (score nodes) |
| `resume_pick` | `only_one`, `first_of_many` | `server._resolve_resume_label` | tool (`load_jd`, and profile tools that start a new thread) |
| `tailor_attempt` | `first`, `retry_after_error` | `server._tailor_retry_update` | tool (`submit_tailor`) |

---

### Task 0: Workspace

- [ ] **Step 1: Create the worktree**

```bash
git fetch origin
git worktree add .worktrees/trace-decision-labels -b feat/trace-decision-labels origin/main
cd .worktrees/trace-decision-labels
uv sync
```

- [ ] **Step 2: Copy this plan into the repo and confirm a green baseline**

```bash
mkdir -p docs/superpowers/plans
cp ~/.claude/plans/lets-go-with-option-wild-stallman.md docs/superpowers/plans/2026-10-11-langsmith-decision-labels.md
uv run pytest -q && uv run ruff check && uv run ruff format --check . && uv run pyright
```

Expected: all pass. If the baseline is red, stop and report; do not fix unrelated failures.

---

### Task 1: `record_decision` helper

**Files:**
- Modify: `callback/observability.py` (imports at top; new block after `_stamp_thread`, around line 164)
- Modify: `tests/conftest.py`
- Modify: `tests/test_observability.py` (append)
- Create: `tests/test_trace_decisions_wire.py`

**Interfaces:**
- Consumes: `langsmith.run_helpers.get_current_run_tree()`.
- Produces: `callback.observability.record_decision(key: str, value: str | bool) -> None`. Pytest fixture `decisions` (a `dict[str, object]` that fills with every accepted label during the test).

- [ ] **Step 1: Add the `decisions` fixture to `tests/conftest.py`**

```python
@pytest.fixture
def decisions(monkeypatch):
    """Capture record_decision labels.

    Stands in for an open LangSmith span: every accepted label lands in the
    returned dict, exactly as it would land in the span's metadata.
    """
    captured: dict[str, object] = {}

    class _FakeRunTree:
        metadata = captured

    monkeypatch.setattr("langsmith.run_helpers.get_current_run_tree", lambda: _FakeRunTree())
    return captured
```

- [ ] **Step 2: Write the failing unit tests (append to `tests/test_observability.py`)**

Add `import logging` and `import pytest` to the imports at the top of that file if they are not already there.

```python
def test_record_decision_stamps_labels_on_the_open_span(decisions):
    from callback.observability import record_decision

    record_decision("jd_source", "fetched")
    record_decision("jd_truncated", True)

    assert decisions == {"jd_source": "fetched", "jd_truncated": True}


def test_record_decision_does_nothing_without_an_open_span(monkeypatch, caplog):
    from callback.observability import record_decision

    caplog.set_level(logging.WARNING, logger="callback.observability")
    monkeypatch.setattr("langsmith.run_helpers.get_current_run_tree", lambda: None)

    record_decision("jd_source", "fetched")

    assert [r.levelname for r in caplog.records] == []


@pytest.mark.parametrize(
    ("key", "value"),
    [
        ("jd_source", "We need a Python engineer"),
        ("jd_source", 3),
        ("JD Source", "fetched"),
    ],
)
def test_record_decision_rejects_anything_that_is_not_a_token(decisions, caplog, key, value):
    from callback.observability import record_decision

    caplog.set_level(logging.WARNING, logger="callback.observability")

    record_decision(key, value)

    actual = {
        "decisions": decisions,
        "levels": [r.levelname for r in caplog.records],
        "value_echoed": "Python engineer" in caplog.text,
    }
    expected = {"decisions": {}, "levels": ["WARNING"], "value_echoed": False}
    assert actual == expected
```

(The existing tests in this file import inside the test function; follow that local pattern here so the `isolate_server_db` fixture's module reloading keeps working.)

- [ ] **Step 3: Run them to see them fail**

Run: `uv run pytest tests/test_observability.py -k record_decision -v`
Expected: FAIL with `ImportError: cannot import name 'record_decision'`.

- [ ] **Step 4: Implement**

In `callback/observability.py`, add to the third-party imports at the top, directly after the `langgraph.types` import:

```python
from langsmith import run_helpers
```

Add after `_stamp_thread`:

```python
# Decision labels are fixed words chosen by the code: lowercase tokens or
# booleans. That shape is the privacy guarantee - a label can never carry JD,
# resume, story, URL, or path text into a trace.
_DECISION_TOKEN_RE = re.compile(r"[a-z0-9_]{1,48}")


def _is_decision_token(value: object) -> bool:
    return isinstance(value, str) and _DECISION_TOKEN_RE.fullmatch(value) is not None


def record_decision(key: str, value: str | bool) -> None:
    """Stamp one code-path decision onto the open LangSmith span's metadata.

    Call it right where the code picks a path, for example
    record_decision("jd_source", "pasted"). Inside a node it lands on that
    node's span; in a tool body it lands on the tool span and on node spans
    created afterwards. With no open span (tracing off, evals) it does nothing.
    """
    if not _is_decision_token(key) or not (isinstance(value, bool) or _is_decision_token(value)):
        logger.warning(
            "decision label %r rejected (value type %s): labels must be booleans or "
            "lowercase [a-z0-9_] tokens of at most 48 characters; nothing was sent to the trace",
            key,
            type(value).__name__,
        )
        return
    run_tree = run_helpers.get_current_run_tree()
    if run_tree is not None:
        run_tree.metadata[key] = value
```

Leave `_stamp_thread` and its in-function import alone (out of scope).

- [ ] **Step 5: Run the unit tests**

Run: `uv run pytest tests/test_observability.py -v`
Expected: all PASS, including every pre-existing test in the file.

- [ ] **Step 6: Write the wire test (`tests/test_trace_decisions_wire.py`)**

This is the one test that uses the real `langsmith.traceable`. It proves labels reach the HTTP payload from a tool body, from a node, and from async code inside a node, and it pins the "tool labels are inherited by later node spans" fact the docs state.

```python
"""End-to-end check that decision labels reach the LangSmith payload.

Real langsmith.traceable, mocked HTTP session: no network.
"""

from __future__ import annotations

import asyncio
import json
from functools import partial
from unittest.mock import MagicMock

from langgraph.graph import END, StateGraph
from langsmith import Client, traceable
from pydantic import BaseModel

import callback.observability as observability

LABEL_KEYS = ("in_tool", "in_node", "in_async", "in_thread")


class _State(BaseModel):
    session_id: str = "s1"
    jd_text: str | None = None


async def _async_work() -> None:
    observability.record_decision("in_async", True)
    await asyncio.to_thread(observability.record_decision, "in_thread", True)


@observability.trace_node("apply", "first")
def _first(state: _State) -> dict:
    asyncio.run(_async_work())
    observability.record_decision("in_node", "yes")
    return {"jd_text": "secret job text"}


def _build_graph():
    builder = StateGraph(_State)
    builder.add_node("first", _first)
    builder.set_entry_point("first")
    builder.add_edge("first", END)
    return builder.compile()


def _labels_sent_on_close(session: MagicMock) -> dict[str, dict]:
    """Per span name: the decision labels in the PATCH that closes the span."""
    sent: dict[str, dict] = {}
    for call in session.request.call_args_list:
        if call.args[0] != "PATCH":
            continue
        body = json.loads(call.kwargs["data"])
        metadata = (body.get("extra") or {}).get("metadata", {})
        sent[body["name"]] = {k: metadata[k] for k in LABEL_KEYS if k in metadata}
    return sent


def test_labels_reach_the_payload_from_tool_node_and_async_code(monkeypatch):
    session = MagicMock()
    client = Client(
        api_url="http://localhost:1984", api_key="x", session=session, auto_batch_tracing=False
    )
    monkeypatch.setenv("CALLBACK_TRACE_BACKEND", "langsmith")
    monkeypatch.setenv("LANGSMITH_TRACING", "true")
    monkeypatch.setenv("LANGSMITH_API_KEY", "lsv2-test")
    monkeypatch.setattr(observability, "_get_traceable", lambda: partial(traceable, client=client))
    graph = _build_graph()

    @observability.trace_tool("load_jd", graph_name="apply")
    def tool(session_id: str) -> dict:
        observability.record_decision("in_tool", "yes")
        observability.invoke_graph_without_native_tracing(
            graph, _State(), {"configurable": {"thread_id": session_id}}
        )
        return {"status": "ok", "session_id": session_id}

    tool("s1")

    actual = _labels_sent_on_close(session)
    expected = {
        "callback.apply.first": {
            "in_tool": "yes",
            "in_node": "yes",
            "in_async": True,
            "in_thread": True,
        },
        "callback.apply.load_jd": {"in_tool": "yes"},
    }
    assert actual == expected
```

- [ ] **Step 7: Run it**

Run: `uv run pytest tests/test_trace_decisions_wire.py -v`
Expected: PASS. If the dict differs, do not loosen the assertion: the difference is the finding. Report it before going on (the rest of the plan and the docs rely on these facts).

- [ ] **Step 8: Full verify and commit**

```bash
uv run pytest -q && uv run ruff check && uv run ruff format --check . && uv run pyright
git add callback/observability.py tests/conftest.py tests/test_observability.py tests/test_trace_decisions_wire.py docs/superpowers/plans/2026-10-11-langsmith-decision-labels.md
git commit -m "feat: add record_decision helper for LangSmith path labels"
```

---

### Task 2: Job-text labels (`jd_source`, `jd_extraction`, `jd_capped`, `jd_truncated`)

**Files:**
- Modify: `callback/apply_nodes.py` (`jd_fetch`, lines 121–172; import line 29)
- Modify: `callback/jd_fetcher.py` (`extract_markdown` ~199, `cap_jd_text` ~253, `_fetch_url_to_markdown_unbounded` ~448; imports)
- Test: `tests/test_jd_fetch_node.py`, `tests/test_jd_fetcher.py`

**Interfaces:**
- Consumes: `record_decision` and the `decisions` fixture from Task 1.
- Produces: the four labels above. No signature changes.

- [ ] **Step 1: Write the failing node tests (append to `tests/test_jd_fetch_node.py`)**

```python
def test_jd_fetch_labels_a_fetched_source(fake_fetch, decisions):
    apply_nodes.jd_fetch(make_state(jd_url="https://example.com/job"))

    assert decisions == {"jd_source": "fetched"}


def test_jd_fetch_labels_a_pasted_source(fake_fetch, decisions):
    apply_nodes.jd_fetch(make_state(jd_raw_text="Python engineer needed"))

    assert decisions == {"jd_source": "pasted"}


def test_jd_fetch_labels_pasted_text_used_after_a_failed_fetch(fake_fetch, decisions):
    _, result = fake_fetch
    result["value"] = OSError("network down")

    apply_nodes.jd_fetch(
        make_state(jd_url="https://example.com/job", jd_raw_text="Python engineer needed")
    )

    assert decisions == {"jd_source": "pasted_after_fetch_failed"}


def test_jd_fetch_failure_without_raw_text_writes_no_source_label(fake_fetch, decisions):
    _, result = fake_fetch
    result["value"] = OSError("network down")

    with pytest.raises(JDFetchError):
        apply_nodes.jd_fetch(make_state(jd_url="https://example.com/job"))

    assert decisions == {}
```

In the same file, change the last assertion of the existing `test_jd_fetch_raw_text_passthrough_unchanged` (the pasted path now announces itself):

```python
    assert jd_log_payloads(caplog) == [
        (
            logging.INFO,
            {"event": "raw_text_used", "session_id": "session-123", "chars": 34},
        )
    ]
```

- [ ] **Step 2: Write the failing fetcher tests (append to `tests/test_jd_fetcher.py`)**

```python
def test_extract_markdown_labels_a_clean_extraction(decisions):
    jd_fetcher.extract_markdown("x" * jd_fetcher.MIN_EXTRACT_CHARS, "", "https://example.com/job")

    assert decisions == {"jd_extraction": "clean"}


def test_extract_markdown_labels_the_body_text_fallback(decisions):
    jd_fetcher.extract_markdown(
        "thin", "y" * jd_fetcher.MIN_EXTRACT_CHARS, "https://example.com/job"
    )

    assert decisions == {"jd_extraction": "body_text"}


def test_extract_markdown_writes_no_label_when_the_page_is_rejected(decisions):
    with pytest.raises(RuntimeError):
        jd_fetcher.extract_markdown("thin", "also thin", "https://example.com/job")

    assert decisions == {}


def test_cap_jd_text_labels_whether_it_cut(decisions):
    jd_fetcher.cap_jd_text("short", "https://example.com/job")
    under_cap = dict(decisions)
    jd_fetcher.cap_jd_text("x" * (jd_fetcher.MAX_JD_CHARS + 5), "https://example.com/job")

    actual = {"under_cap": under_cap, "over_cap": decisions}
    expected = {"under_cap": {"jd_capped": False}, "over_cap": {"jd_capped": True}}
    assert actual == expected


def test_fetch_url_to_markdown_labels_a_truncated_page(monkeypatch, decisions):
    _fake_playwright(monkeypatch)
    monkeypatch.setattr(
        jd_fetcher,
        "extract_markdown",
        lambda *_: "**Minimum Qualifications:**\n\n**Preferred Qualifications:**\n\n- Python\n",
    )

    asyncio.run(jd_fetcher.fetch_url_to_markdown("https://example.com/job"))

    assert decisions == {"jd_capped": False, "jd_truncated": True}
```

- [ ] **Step 3: Run to see them fail**

Run: `uv run pytest tests/test_jd_fetch_node.py tests/test_jd_fetcher.py -v`
Expected: the new tests FAIL (`decisions == {}`), and `test_jd_fetch_raw_text_passthrough_unchanged` FAILS on the log assertion.

- [ ] **Step 4: Implement in `callback/apply_nodes.py`**

Change the import on line 29 to:

```python
from callback.observability import record_decision, trace_node
```

In `jd_fetch`, add one line in each of three places.

Fallback branch (inside `if state.jd_raw_text:` under the `except`):

```python
            if state.jd_raw_text:
                _log_jd_fetch(logging.WARNING, "fallback_used", **error_fields)
                record_decision("jd_source", "pasted_after_fetch_failed")
                return {"jd_text": state.jd_raw_text}
```

Success branch:

```python
        _log_jd_fetch(logging.INFO, "fetch_ok", **log_fields)
        record_decision("jd_source", "fetched")
        return {"jd_text": markdown}
```

No-URL branch (this path logged nothing before):

```python
    if state.jd_raw_text:
        _log_jd_fetch(
            logging.INFO,
            "raw_text_used",
            session_id=state.session_id,
            chars=len(state.jd_raw_text),
        )
        record_decision("jd_source", "pasted")
        return {"jd_text": state.jd_raw_text}
```

- [ ] **Step 5: Implement in `callback/jd_fetcher.py`**

Add a first-party import block after the `playwright` import, separated from it by one blank line (ruff's import-order rule needs the blank line):

```python
from playwright.async_api import ViewportSize, async_playwright

from callback.observability import record_decision
```

`extract_markdown` (the label is written only when a result is returned):

```python
    result = extracted
    extraction = "clean"
    if len(extracted) < MIN_EXTRACT_CHARS and len(body_text) >= MIN_EXTRACT_CHARS:
        _log(
            "fetch_thin_extraction",
            url=url,
            extracted_chars=len(extracted),
            body_chars=len(body_text),
        )
        result = body_text
        extraction = "body_text"
    if len(result) < MIN_EXTRACT_CHARS:
        _log(
            "fetch_thin",
            url=url,
            extracted_chars=len(extracted),
            body_chars=len(body_text),
            min_chars=MIN_EXTRACT_CHARS,
        )
        raise RuntimeError(f"thin page: {len(result)} chars, under the {MIN_EXTRACT_CHARS} minimum")
    record_decision("jd_extraction", extraction)
    return result
```

`cap_jd_text`:

```python
    if len(text) <= MAX_JD_CHARS:
        record_decision("jd_capped", False)
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
    record_decision("jd_capped", True)
    return capped
```

`_fetch_url_to_markdown_unbounded`:

```python
        empty_sections = find_empty_sections(result)
        if empty_sections:
            _log("fetch_truncated", url=url, empty_sections=empty_sections)
        record_decision("jd_truncated", bool(empty_sections))
        return result
```

- [ ] **Step 6: Run, including the eval fetch path and the existing import-weight test**

Run: `uv run pytest tests/test_jd_fetch_node.py tests/test_jd_fetcher.py evals/test_fetch_recall.py -m "not local" -v`
Expected: all PASS. This includes the existing test near `tests/test_jd_fetcher.py:794` that checks importing the fetcher does not load `trafilatura`; it must stay green.

- [ ] **Step 7: Full verify and commit**

```bash
uv run pytest -q && uv run ruff check && uv run ruff format --check . && uv run pyright
git add callback/apply_nodes.py callback/jd_fetcher.py tests/test_jd_fetch_node.py tests/test_jd_fetcher.py
git commit -m "feat: label the job-text source, fallback, cap and truncation in traces"
```

---

### Task 3: Resume, years, and retry labels

**Files:**
- Modify: `callback/apply_nodes.py` (`parse_initial` ~236, `score_initial` ~276, `_candidate_experience_years` ~375, `score_final` ~560)
- Modify: `callback/server.py` (`_resolve_resume_label` ~636, `_tailor_retry_update` ~1098; the existing `callback.observability` import)
- Test: `tests/test_apply_nodes.py`, `tests/test_server.py`

**Interfaces:**
- Consumes: `record_decision` (already imported in `apply_nodes.py` by Task 2), `decisions` fixture.
- Produces: labels `initial_score_source`, `experience_years`, `experience_evaluated`, `resume_pick`, `tailor_attempt`. No signature changes.

- [ ] **Step 1: Write the failing tests in `tests/test_server.py`**

Add `from types import SimpleNamespace` to the imports at the top. Append after the existing `MINIMAL_SECTIONS_JSON` constant (it has one experience entry with no dates):

```python
def test_parse_initial_labels_the_resume_file_as_score_source(tmp_path, decisions):
    from callback.apply_nodes import parse_initial
    from callback.state import ApplyState

    resume = tmp_path / "resume.txt"
    resume.write_text("Lead Engineer with Python and Kubernetes experience")

    with patch("callback.apply_nodes.get_resume", return_value=str(resume)):
        parse_initial(ApplyState(session_id="s1", resume_label="lead"))

    assert decisions == {"initial_score_source": "resume_file"}


def test_parse_initial_labels_sections_text_when_the_resume_file_is_missing(decisions):
    from callback.apply_nodes import parse_initial
    from callback.repository.resumes import ResumeNotFoundError
    from callback.state import ApplyState

    with (
        patch(
            "callback.apply_nodes._load_wiki_sections",
            return_value=(MINIMAL_SECTIONS_JSON, "index", "sections text"),
        ),
        patch("callback.apply_nodes.get_resume", side_effect=ResumeNotFoundError("ghost")),
    ):
        result = parse_initial(ApplyState(session_id="s1", resume_label="ghost"))

    actual = {"parsed_initial": result["parsed_initial"], "decisions": decisions}
    expected = {
        "parsed_initial": "sections text",
        "decisions": {"experience_years": "unavailable", "initial_score_source": "sections_text"},
    }
    assert actual == expected


def test_parse_initial_labels_no_source_when_nothing_is_available(decisions):
    from callback.apply_nodes import parse_initial
    from callback.repository.resumes import ResumeNotFoundError
    from callback.state import ApplyState

    parse_initial(ApplyState(session_id="s1"))
    no_label = dict(decisions)
    decisions.clear()
    with patch("callback.apply_nodes.get_resume", side_effect=ResumeNotFoundError("ghost")):
        parse_initial(ApplyState(session_id="s1", resume_label="ghost"))

    actual = {"no_label": no_label, "resume_not_found": decisions}
    expected = {
        "no_label": {"initial_score_source": "none"},
        "resume_not_found": {"initial_score_source": "none"},
    }
    assert actual == expected


def test_resolve_resume_label_labels_the_pick(decisions):
    import callback.server as server

    with patch("callback.server.list_resumes", return_value=["a"]):
        server._resolve_resume_label("sess-1")
    one = dict(decisions)
    with patch("callback.server.list_resumes", return_value=["a", "b"]):
        server._resolve_resume_label("sess-1")

    actual = {"one": one, "several": decisions}
    expected = {"one": {"resume_pick": "only_one"}, "several": {"resume_pick": "first_of_many"}}
    assert actual == expected


class _FakeApplyGraph:
    def __init__(self, values: dict) -> None:
        self._values = values
        self.updates: list[dict] = []

    def get_state(self, config):
        return SimpleNamespace(values=self._values)

    def update_state(self, config, update, as_node):
        self.updates.append(update)


def test_tailor_retry_update_labels_the_attempt(decisions):
    import callback.server as server

    server._tailor_retry_update(_FakeApplyGraph({}), {}, {"no_coverage": True}, "sess-1")
    first = dict(decisions)
    server._tailor_retry_update(
        _FakeApplyGraph({"error": "render: boom"}), {}, {"no_coverage": True}, "sess-1"
    )

    actual = {"first": first, "retry": decisions}
    expected = {
        "first": {"tailor_attempt": "first"},
        "retry": {"tailor_attempt": "retry_after_error"},
    }
    assert actual == expected
```

- [ ] **Step 2: Write the failing tests in `tests/test_apply_nodes.py`**

The file already imports `ApplyState`, `ExperienceEntry` and `_candidate_experience_years`. Add `score_final` and `score_initial` to the existing `from callback.apply_nodes import (...)` block if they are not there. Append:

```python
class TestDecisionLabels:
    def test_experience_years_computed(self, decisions):
        experience = [
            ExperienceEntry(company="A", role="Eng", start_date="2020-01", end_date="2020-12")
        ]

        _candidate_experience_years(experience)

        assert decisions == {"experience_years": "computed"}

    def test_experience_years_partial_when_an_entry_is_skipped(self, decisions):
        experience = [
            ExperienceEntry(company="A", role="Eng", start_date="2020-01", end_date="2020-12"),
            ExperienceEntry(company="B", role="Eng", start_date="??", end_date=None),
        ]

        _candidate_experience_years(experience)

        assert decisions == {"experience_years": "partial"}

    def test_experience_years_unavailable(self, decisions):
        experience = [ExperienceEntry(company="A", role="Eng", start_date="??", end_date=None)]

        _candidate_experience_years(experience)

        assert decisions == {"experience_years": "unavailable"}

    def test_score_nodes_label_whether_experience_was_scored(self, decisions):
        keywords = {"required": ["Python"], "preferred": [], "required_years": 0}

        initial = score_initial(
            ApplyState(session_id="s", parsed_initial="Python engineer", keywords=keywords)
        )
        after_initial = dict(decisions)
        decisions.clear()
        final = score_final(
            ApplyState(session_id="s", parsed_final="Python engineer", keywords=keywords)
        )

        actual = {"initial": after_initial, "final": decisions}
        expected = {
            "initial": {"experience_evaluated": initial["score_initial"]["experience_evaluated"]},
            "final": {"experience_evaluated": final["score_final"]["experience_evaluated"]},
        }
        assert actual == expected
```

- [ ] **Step 3: Run to see them fail**

Run: `uv run pytest tests/test_apply_nodes.py tests/test_server.py -k "label or Decision" -v`
Expected: FAIL with empty `decisions` dicts.

- [ ] **Step 4: Implement in `callback/apply_nodes.py`**

`parse_initial`: three added lines.

```python
    if state.resume_label is None:
        record_decision("initial_score_source", "none")
        return {"parsed_initial": "<noop:parse:no-source>"}
```

Inside `except ResumeNotFoundError:`, after the existing `logger.warning(...)` and before the `return`:

```python
        record_decision("initial_score_source", "sections_text" if sections_json else "none")
        return {**base, "parsed_initial": fallback}
```

End of the function:

```python
    text = resume_extractor.extract(resume_path)
    record_decision("initial_score_source", "resume_file")
    return {**base, "parsed_initial": text}
```

`_candidate_experience_years`: replace the last three lines.

```python
    if not intervals:
        record_decision("experience_years", "unavailable")
        return None
    record_decision("experience_years", "partial" if skipped else "computed")
    return round(_merge_interval_months(intervals) / 12, 2)
```

`score_initial`: new body after `_log_enter(...)`.

```python
    score = _run_score(
        state.parsed_initial,
        state.keywords,
        closeable_by="source_pdf",
        candidate_years=state.candidate_years,
    )
    record_decision("experience_evaluated", score["experience_evaluated"])
    return {"score_initial": score}
```

`score_final`: new body after `_log_enter(...)`.

```python
    score = _run_score(
        state.parsed_final,
        state.keywords,
        closeable_by="render",
        candidate_years=state.candidate_years,
    )
    record_decision("experience_evaluated", score["experience_evaluated"])
    return {"score_final": score}
```

- [ ] **Step 5: Implement in `callback/server.py`**

Add `record_decision` to the existing `from callback.observability import ...` statement (keep the names in alphabetical order).

`_resolve_resume_label`, last line before `return registered[0], None`:

```python
    record_decision("resume_pick", "first_of_many" if len(registered) > 1 else "only_one")
    return registered[0], None
```

`_tailor_retry_update`: replace `if snapshot.values.get("error"):` and the two lines above it with this; leave the body of the `if` unchanged.

```python
    snapshot = graph.get_state(config)
    update = values
    retrying = bool(snapshot.values.get("error"))
    record_decision("tailor_attempt", "retry_after_error" if retrying else "first")
    if retrying:
```

- [ ] **Step 6: Run**

Run: `uv run pytest tests/test_apply_nodes.py tests/test_server.py tests/test_server_profile.py tests/test_apply_e2e.py tests/test_submit_tailor.py -q`
Expected: all PASS.

- [ ] **Step 7: Full verify and commit**

```bash
uv run pytest -q && uv run ruff check && uv run ruff format --check . && uv run pyright
git add callback/apply_nodes.py callback/server.py tests/test_apply_nodes.py tests/test_server.py
git commit -m "feat: label resume source, years path, resume pick and tailor retry in traces"
```

---

### Task 4: Make the tracing docs match the code

**Files:**
- Modify: `AGENTS.md` (lines ~168–175; the text to replace starts mid-line, after "Restart the MCP host after config changes.")
- Modify: `CLAUDE.md` (Env Vars section, the paragraph starting "Tracing metadata must stay safe")
- Modify: `README.md` (line ~186 in "What happens to your resume"; lines ~229–231 in "Tracing details")
- Modify: `callback/observability.py` (two comments, lines ~333–335 and ~339–341)
- Test: `tests/test_observability.py` (one pinning test)

**Interfaces:** none.

- [ ] **Step 1: Pin the one doc claim that has no test yet (append to `tests/test_observability.py`)**

`get_wiki_pages` replies with `data={"pages": {...}}` (`callback/server.py:1903`). Those pages are not in the list of profile fields that get cut to counts, so they pass through.

```python
def test_sanitize_tool_output_sends_wiki_pages_as_text():
    """get_wiki_pages replies pass through: page content is not cut to counts."""
    from callback.observability import _sanitize_tool_output

    envelope = {
        "session_id": "s1",
        "status": "ok",
        "data": {"pages": {"experience/story-001.md": "# Cut p95 latency\n\nRebuilt the cache."}},
    }

    actual = _sanitize_tool_output(envelope)

    expected = {
        "session_id": "s1",
        "status": "ok",
        "data": {"pages": {"experience/story-001.md": "# Cut p95 latency\n\nRebuilt the cache."}},
    }
    assert actual == expected
```

Run: `uv run pytest tests/test_observability.py -k wiki_pages -v`
Expected: PASS straight away (it pins existing behavior). If it fails, the docs text in Step 2 about wiki pages is wrong: stop and report.

- [ ] **Step 2: `AGENTS.md` and `CLAUDE.md`: replace the old "safe metadata" sentences**

In `AGENTS.md`, replace from "Tracing is opt-in; trace metadata must stay safe and compact:" through "...but never raw values or file paths." In `CLAUDE.md`, replace from "Tracing metadata must stay safe:" through "...and state/update key names." Keep the sentences about `callback trace-check` and native auto-tracing that follow.

New text (same in both files):

```markdown
Tracing is opt-in. What a trace contains depends on the span type:

- **Tool spans** (`trace_tool`) send these arguments when present: `session_id`,
  `jd_url`, `jd_raw_text`, `jd_json`, `edits`, `page_ids`, `no_coverage`,
  `resume_label`, `output_dir`. Other arguments (resume and file paths passed to
  the profile tools, story intake, host tags) are not sent. The tool's reply is
  sent whole, with two cuts:
  - `email` and `phone` fields become placeholders anywhere, and email- and
    phone-shaped text is masked inside any string. Name, location, address and
    links become placeholders only inside a structured contact block; a name
    written inside free text or a wiki page is not caught.
  - Stored profile content (`compiled_profile`, `sections`, `intake`, skill
    lists, `primary_skill`, `story_id`) becomes counts and key names. Pages
    returned by `get_wiki_pages` are the exception: they are sent as text.
- **Node spans** (`trace_node`) send lengths, key names, booleans, the two
  page-count numbers, and identifiers (`session_id`, graph and node names,
  status, error stage and code, exception class name). Never content.
- **Decision labels** (`record_decision`) say which path the code took, as span
  metadata, for example `jd_source=pasted`. Labels are booleans or lowercase
  `[a-z0-9_]` tokens, never content. A label set inside a node appears on that
  node's span. A label set in a tool body appears on the tool span and on every
  node span created after it.

API keys never go into a trace. Do not widen what node spans send.
```

- [ ] **Step 3: Label table: `AGENTS.md` only, directly under the text from Step 2**

```markdown
| Label | Values | Meaning |
|---|---|---|
| `jd_source` | `fetched`, `pasted`, `pasted_after_fetch_failed` | Where the job text came from |
| `jd_extraction` | `clean`, `body_text` | Clean extraction, or whole-page text because the extraction was too short |
| `jd_capped` | true/false | Job text was cut at the 16,000-character cap |
| `jd_truncated` | true/false | Headings with no text under them: the page looks cut off |
| `initial_score_source` | `resume_file`, `sections_text`, `none` | Which text the first score was computed from |
| `experience_years` | `computed`, `partial`, `unavailable` | Whether every job entry's dates could be read |
| `experience_evaluated` | true/false | False means the total was renormalized without ExperienceFit |
| `resume_pick` | `only_one`, `first_of_many` | Several resumes registered: the first was used |
| `tailor_attempt` | `first`, `retry_after_error` | Whether this `submit_tailor` call is a retry |
```

In `CLAUDE.md`, add one line under the text from Step 2 instead of the table:

```markdown
The list of decision labels is in `AGENTS.md`, in the same section.
```

- [ ] **Step 4: `README.md` line ~186: replace the last sentence of the paragraph**

Old:

```
And if you turn on LangSmith tracing, which is off by default, it sends traces that are redacted to exclude your resume text, posting text, story content, your edits, and your file paths.
```

New:

```
And if you turn on LangSmith tracing, which is off by default, it sends traces to your own LangSmith project. Those traces include the posting text, the extracted keywords, your submitted edits, the wiki pages your client asked for (including story text), and output paths. Email addresses and phone numbers are masked, the contact block of your resume is replaced with placeholders, and your stored profile and resume sections are reduced to counts.
```

- [ ] **Step 5: `README.md` "Tracing details": replace the final paragraph**

Old:

```
Spans carry only safe fields: `session_id`, `tool_name`, `graph_name`, `node_name`,
`resume_label`, counts, and key names. Never resume text, posting text, story content,
submitted edits, file paths, or API keys.
```

New:

```
Tool spans carry the tool's main arguments and its reply, with emails, phone numbers and
the resume contact block masked and stored profile content reduced to counts. Wiki pages
your client requests are sent as text. Node spans carry only lengths, key names, booleans
and identifiers. Each span also carries short labels that say which path the code took,
such as `jd_source=pasted` or `jd_truncated=true`. API keys are never sent.
```

- [ ] **Step 6: Correct the two comments in `callback/observability.py`**

In `_sanitize_tool_output`, replace the three-line comment with:

```python
    # Contact PII is stripped from the envelope. Stored profile content
    # (compiled_profile, sections, intake, skill fields) is summarized to counts
    # and key names. Everything else passes through as is, including JD text,
    # score gaps, and the page text returned by get_wiki_pages.
```

Above `_SPAN_MAPPING_EXEMPT_KEYS`, replace the three-line comment with:

```python
# Span-summarization contract for LangGraph node traces (see the tracing section
# of AGENTS.md): lengths, key names, booleans, counts and identifiers only -
# never resume text, JD text, wiki content, story narratives, or skill names.
```

- [ ] **Step 7: Check nothing else repeats the old claim**

Run: `git grep -n -i -E "never resume text|redacted to exclude|must stay safe|posting text" -- ':!CHANGELOG.md' ':!docs/retros' ':!docs/superpowers' ':!tests'`
Expected: the only hits are the new README sentences from Steps 4–5 (they contain "posting text") and the comment from Step 6. Skill files and plugin manifests are covered by this search; if one still claims traces leave out posting text, edits, or paths, fix it in the same style. `CHANGELOG.md`, `docs/retros/` and old plans are history: leave them.

- [ ] **Step 8: Full verify and commit**

```bash
uv run pytest -q && uv run ruff check && uv run ruff format --check . && uv run pyright
git add AGENTS.md CLAUDE.md README.md callback/observability.py tests/test_observability.py
git commit -m "docs: describe what LangSmith traces really contain"
```

---

### Task 5: Review, pull request, follow-up issue

- [ ] **Step 1: Review the whole branch** with one fresh reviewer (superpowers:requesting-code-review, Opus). Fix what it finds, re-run the four verify commands.

- [ ] **Step 2: Open the PR**

Write `$SCRATCH/pr-body.md` through the `humanizer` skill. It must cover:

- What changed: one helper, nine labels, corrected tracing docs.
- Why: the Lyra Health posting that was fetched cut off with no sign of it in the trace.
- How it was tested: the wire test with real `traceable`, plus the unit tests.
- A plain note that tool spans already sent content before this PR; the PR documents it and does not change it.
- "Not in this PR", with the ten labels that were considered and left out: `route_after_tailor`, `route_after_render`, `route_after_parse_final`, `route_after_finalize`, `tailor_path`, `ats_input_suspect`, `route_after_check_profile`, `route_after_check_orphans`, `resume_label_source`, `orphans_source`. Say why: the list of node spans already shows the route, and nobody has needed the others yet.
- The attribution line from Global Constraints.

```bash
git push -u origin feat/trace-decision-labels
gh pr create --base main --head feat/trace-decision-labels --title "Show which path the code took in LangSmith traces; correct the tracing docs" --body-file $SCRATCH/pr-body.md
```

Report the URL. Then follow the owner's Codex review wait loop (poll at 5 and 10 minutes; fix comments and re-push).

- [ ] **Step 3: Open the follow-up issue** (the owner's own repo, so post directly)

Write `$SCRATCH/issue-body.md` through the `humanizer` skill:

- Problem: when a posting looks cut off (`jd_truncated`) or came from pasted text, only LangSmith and the log know. The model that extracts keywords and the final report are never told, so a resume can be scored against half a job description with no warning. That goes against the North Star rule to surface real gaps.
- Proposal: add `jd_source` and `jd_truncated` to the apply graph state, return them in the `load_jd` reply, and show a note in the report when the posting looked cut off.
- Notes: this changes the tool reply and the state schema, so the skill instructions and `test_apply_e2e.py` need updating. `fetch_url_to_markdown` returns a bare string today and the evals call it, so the fetcher needs a second way to hand back these facts.

```bash
gh issue create --title "Tell the model and the report when a job posting looks cut off" --body-file $SCRATCH/issue-body.md
```

Report the URL.

- [ ] **Step 4: Live check. MAIN SESSION ONLY, not a subagent task** (needs the network, LinkedIn, and the owner's real LangSmith key).

First confirm tracing is set up for the CLI on this machine:

```bash
uv run callback config status
```

If it does not show `CALLBACK_TRACE_BACKEND=langsmith` and a LangSmith key, stop and ask the owner to run `uv run callback config langsmith` themselves (entering the key is theirs to do), then `uv run callback trace-check --emit-test-trace`. `~/.config/callback/env.json` did not exist when this plan was written, so expect to need this.

Then fetch the posting that was cut off, on the branch, calling only `load_jd` (the smoke script does more and can fail on a real posting). The settings file is loaded inside the process, so the API key never appears on a command line or in output:

```bash
uv run python -c "
import time
from callback import settings
settings.apply_env_file()
from callback.server import load_jd
reply = load_jd(jd_url='https://www.linkedin.com/jobs/view/4473077871/')
print(reply['status'], reply.get('session_id'))
time.sleep(8)
"
```

Read the labels back:

```bash
uv run python -c "
import os
from callback import settings
settings.apply_env_file()
from langsmith import Client
project = os.environ.get('LANGSMITH_PROJECT', 'Callback')
runs = list(Client().list_runs(project_name=project, filter='eq(name, \"callback.apply.jd_fetch\")', limit=1))
metadata = (runs[0].extra or {}).get('metadata', {})
print(runs[0].start_time, {k: metadata.get(k) for k in ('jd_source', 'jd_extraction', 'jd_capped', 'jd_truncated', 'resume_pick')})
"
```

Expected: a start time from the last minute, and `jd_source: fetched`, `jd_extraction: clean` or `body_text`, `jd_capped: False`, `jd_truncated: True` or `False`, `resume_pick: only_one` or `first_of_many`, with no `None` values. If any value is `None`, or the start time is old, report it on the PR and to the owner. (If LinkedIn refuses the fetch, `load_jd` returns an error and no `jd_source` is written; use a Greenhouse posting from the owner's log instead.)

---

## Out of scope (do not build)

- Returning `jd_source` / `jd_truncated` to the model, or putting them in the report. Tracked by the issue from Task 5 Step 3.
- The ten labels listed in Task 5 Step 2.
- A setting to cut tool spans down to counts.
- Copying node labels up to the tool span.
- `_stamp_thread`'s in-function import, and `check_orphans` returning `[]` on a missing profile without a log line. Both predate this plan.

## Verification (end to end)

1. `uv run pytest -q && uv run ruff check && uv run ruff format --check . && uv run pyright` green.
2. `uv run pytest tests/test_trace_decisions_wire.py -v` passes: labels reach the HTTP payload from a tool body, a node, and async code.
3. `uv run pytest -m "not local" evals/` passes: the eval fetch path still works with the fetcher's new import.
4. Live check from Task 5 Step 4: the newest `jd_fetch` span in LangSmith carries the job-text labels.
