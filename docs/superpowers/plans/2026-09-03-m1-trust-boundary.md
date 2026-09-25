# M1 — Close the Trust Boundary: Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Ship defects D1, D2, D3, D6, D7 from `INTENT.md` so host-supplied wiki page ids cannot escape the wiki root, re-onboarding replaces the resume, `server.log` has one line per event, a bare year range is not read as a phone number, and extractor errors come back as error envelopes.

**Architecture:** Five small, independent fixes in existing modules. No new modules, no new dependencies, no new abstractions. Each fix is a guard in the one shared function all callers route through (`WikiStore._page_path`, `_route_check_profile`, `_log`, `_extract_phone_candidate`, and one `except Exception` per apply tool that mirrors `load_jd`).

**Tech Stack:** Python 3.12, LangGraph, FastMCP, pytest, ruff, pyright. Run everything with `uv run ...`.

**Spec:** `INTENT.md` (section "Current state (2026-09-03)" defect table, and "M1 — Close the trust boundary").

## Global Constraints

- Branch: `feat/m1-trust-boundary`, PR targets `main` (one PR per milestone).
- Every task must leave `uv run pytest -q`, `uv run ruff check .`, `uv run ruff format --check .`, and `uv run pyright` green. CI runs all four.
- ruff: line length 100, `max-complexity = 7` (C901). Do not add nesting; split helpers if a function would exceed complexity 7.
- Tests assert with full-object equality (`assert actual == expected` on whole dicts), not piecemeal key checks.
- No silent failures, no hidden fallbacks. Every caught exception is logged with `_log_exception` before an envelope is returned.
- Touch only the files listed in each task. Do not refactor neighbouring code.
- Commit message format: conventional commits (`fix(wiki): ...`). End each commit body with:
  ```
  Co-Authored-By: Claude Fable 5.1 <noreply@anthropic.com>
  Claude-Session: https://claude.ai/code/session_01CBmQfLDXe6dxY5JVQnvHcz
  ```
- Test isolation: `tests/conftest.py` has an autouse fixture that patches `Path.home()` to `tmp_path` and re-imports `callback.server`, `callback.apply_graph`, `callback.profile_graph` per test. Import those modules *inside* test functions (existing tests do this) so they pick up the fresh module.

---

### Task 1: D1 — Confine wiki page ids to the wiki root

**Files:**
- Modify: `callback/wiki.py:35-55` (`write_page`, `read_pages`)
- Modify: `callback/server.py:1438-1439` (`_get_wiki_pages_impl`, the `store.read_pages(...)` call)
- Test: `tests/test_wiki.py`, `tests/test_server.py`

**Interfaces:**
- Consumes: `WikiStore.wiki_root(resume_label) -> Path` (exists), `_err(stage, code, message, session_id=None, retriable=False) -> str` (exists in `server.py:489`).
- Produces: `WikiStore._page_path(resume_label: str, page_id: str) -> Path` which raises `ValueError` with message `page_id escapes wiki root: <page_id!r>` when the resolved path is outside the resolved wiki root. `get_wiki_pages` returns error code `invalid_page_id`, `retriable=True` for such ids.

Background: `read_pages` does `root / page_id`. A host-supplied id like `../../../../etc/passwd` or an absolute path (`Path / "/abs"` yields `/abs`) resolves outside the wiki and its content is returned to the host. JD text is untrusted web content that reaches the host before the host calls back, so page ids are a trust boundary.

- [ ] **Step 1: Write the failing tests in `tests/test_wiki.py`**

Append to the file (it already imports `wiki_module`, `WikiStore`, and has a `store(tmp_path, monkeypatch)` helper that sets `BASE_DIR = tmp_path`). Add `import pytest` at the top.

```python
def test_read_pages_rejects_parent_traversal(tmp_path, monkeypatch):
    s = store(tmp_path, monkeypatch)
    outside = tmp_path.parent / "outside-secret.txt"
    outside.write_text("hunter2", encoding="utf-8")
    with pytest.raises(ValueError, match="escapes wiki root"):
        s.read_pages("r", ["../../outside-secret.txt"])


def test_read_pages_rejects_absolute_path(tmp_path, monkeypatch):
    s = store(tmp_path, monkeypatch)
    outside = tmp_path.parent / "outside-secret.txt"
    outside.write_text("hunter2", encoding="utf-8")
    with pytest.raises(ValueError, match="escapes wiki root"):
        s.read_pages("r", [str(outside)])


def test_write_page_rejects_parent_traversal(tmp_path, monkeypatch):
    s = store(tmp_path, monkeypatch)
    with pytest.raises(ValueError, match="escapes wiki root"):
        s.write_page("r", "../escaped.md", "x")


def test_read_pages_allows_nested_ids(tmp_path, monkeypatch):
    s = store(tmp_path, monkeypatch)
    s.write_page("r", "experience/acme.md", "acme")
    assert s.read_pages("r", ["experience/acme.md", "./experience/acme.md"]) == {
        "experience/acme.md": "acme",
        "./experience/acme.md": "acme",
    }
```

Note on the traversal test: `BASE_DIR` is `tmp_path`, so wiki root is `tmp_path/r`; `../../outside-secret.txt` resolves to `tmp_path.parent/outside-secret.txt`, which is outside `tmp_path/r`. Do not write the secret file inside `tmp_path` or the traversal would land inside `BASE_DIR` and the test would be meaningless.

- [ ] **Step 2: Run tests to verify they fail**

Run: `uv run pytest tests/test_wiki.py -q`
Expected: 3 FAIL (`DID NOT RAISE`), `test_read_pages_allows_nested_ids` PASS.

- [ ] **Step 3: Implement `_page_path` and route `write_page` / `read_pages` through it**

Replace `write_page` and `read_pages` in `callback/wiki.py`:

```python
    def _page_path(self, resume_label: str, page_id: str) -> Path:
        """Resolve page_id under the wiki root; reject ids that escape it."""
        root = self.wiki_root(resume_label).resolve()
        path = (root / page_id).resolve()
        if not path.is_relative_to(root):
            raise ValueError(f"page_id escapes wiki root: {page_id!r}")
        return path

    def write_page(self, resume_label: str, page_id: str, content: str) -> None:
        """Write any page by page_id (path relative to wiki_root)."""
        p = self._page_path(resume_label, page_id)
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(content, encoding="utf-8")

    def read_index(self, resume_label: str) -> str | None:
        p = self.wiki_root(resume_label) / "index.md"
        return p.read_text(encoding="utf-8") if p.exists() else None

    def read_pages(self, resume_label: str, page_ids: list[str]) -> dict[str, str]:
        """Return {page_id: content} for each requested page.

        Missing pages return empty string. Raises ValueError for a page_id
        that resolves outside the wiki root.
        """
        result = {}
        for page_id in page_ids:
            p = self._page_path(resume_label, page_id)
            result[page_id] = p.read_text(encoding="utf-8") if p.exists() else ""
        return result
```

`Path.resolve()` works on non-existent paths and follows symlinks on both sides, so a symlinked `tmp` does not produce false rejections.

- [ ] **Step 4: Run wiki tests to verify they pass**

Run: `uv run pytest tests/test_wiki.py -q`
Expected: all PASS.

- [ ] **Step 5: Write the failing server test in `tests/test_server.py`**

Append after `test_get_wiki_pages_returns_submit_tailor_workflow` (around line 1010). It reuses that test's setup shape.

```python
def test_get_wiki_pages_rejects_page_id_outside_wiki_root(tmp_path, monkeypatch):
    from callback.server import get_wiki_pages, load_jd, submit_keywords
    from callback.wiki import WikiStore

    resume_label = "wiki_pages_traversal_resume"
    monkeypatch.setattr("callback.wiki.BASE_DIR", tmp_path / "wiki")
    sections = {
        "summary": "Python engineer",
        "skills": {"flat": ["Python"], "categorized": {}},
        "experience": [{"company": "ACME", "role": "Engineer", "bullets": ["Built Python"]}],
        "projects": [],
        "education": [],
        "contact": {"name": "Jane Dev"},
        "certifications": [],
        "awards": [],
    }
    store = WikiStore()
    store.write_page(resume_label, "sections.json", json.dumps(sections))
    store.write_index(resume_label, "- experience/acme.md")
    secret = tmp_path / "secret.txt"
    secret.write_text("hunter2", encoding="utf-8")

    with patch("callback.server.list_resumes", return_value=[resume_label]):
        loaded = json.loads(load_jd(jd_raw_text="Python engineer needed"))
    session_id = loaded["session_id"]
    json.loads(submit_keywords(session_id=session_id, jd_json=PARTIAL_JD_JSON))

    result = json.loads(get_wiki_pages(session_id=session_id, page_ids=["../../secret.txt"]))

    expected = {
        "status": "error",
        "error": {
            "stage": "get_wiki_pages",
            "code": "invalid_page_id",
            "message": "page_id escapes wiki root: '../../secret.txt'",
            "retriable": True,
        },
        "session_id": session_id,
    }
    assert result == expected
```

- [ ] **Step 6: Run the server test to verify it fails**

Run: `uv run pytest tests/test_server.py::test_get_wiki_pages_rejects_page_id_outside_wiki_root -q`
Expected: FAIL — the tool raises `ValueError` instead of returning an envelope.

- [ ] **Step 7: Catch the `ValueError` in `_get_wiki_pages_impl`**

In `callback/server.py`, replace:

```python
    store = WikiStore()
    pages = store.read_pages(resume_label, page_ids)
```

with:

```python
    try:
        pages = WikiStore().read_pages(resume_label, page_ids)
    except ValueError as exc:
        _log("WARNING", {"tool": "get_wiki_pages", "session_id": session_id, "event": "invalid_page_id"})
        return _err(
            stage="get_wiki_pages",
            code="invalid_page_id",
            message=str(exc),
            session_id=session_id,
            retriable=True,
        )
```

Do not put the page id in the log payload (untrusted host input; trace metadata must stay safe).

- [ ] **Step 8: Run the full gate**

Run: `uv run pytest -q && uv run ruff check . && uv run ruff format --check . && uv run pyright`
Expected: all green. If ruff format complains, run `uv run ruff format callback/wiki.py callback/server.py tests/test_wiki.py tests/test_server.py`.

- [ ] **Step 9: Commit**

```bash
git add callback/wiki.py callback/server.py tests/test_wiki.py tests/test_server.py
git commit -m "fix(wiki): confine page ids to the wiki root

get_wiki_pages accepted host-supplied ids like ../../x and returned any
readable file. WikiStore now resolves every page id under the wiki root
and rejects escapes; the tool returns an invalid_page_id envelope.

Closes D1 in INTENT.md.

Co-Authored-By: Claude Fable 5.1 <noreply@anthropic.com>
Claude-Session: https://claude.ai/code/session_01CBmQfLDXe6dxY5JVQnvHcz"
```

---

### Task 2: D2 — Re-onboarding with an existing profile replaces the resume

**Files:**
- Modify: `callback/profile_graph.py:50-52` (`_route_check_profile`)
- Test: `tests/test_profile_graph.py`

**Interfaces:**
- Consumes: `ProfileState.resume_path`, `ProfileState.profile_exists` (exist in `callback/state.py:78-91`); `onboard` node already calls `clear_resumes()` then `save_resume("primary", path)`.
- Produces: `_route_check_profile(state) -> str` returns `"onboard"` when `state.resume_path` is set, regardless of `profile_exists`.

Background: `onboard_user` always enters the graph at `check_profile`. Today the router sends an existing profile straight to `check_orphans`, so the `onboard` node (which replaces the stored resume) never runs. If the profile has orphaned skills the graph then enters `create_story` with no story intake and crashes; with no orphans it silently ends without touching the resume. The intent of a call that carries `resume_path` is "register this resume", so route on that.

- [ ] **Step 1: Write the failing tests in `tests/test_profile_graph.py`**

Add to the `TestCheckProfileRouter` class (after `test_routes_to_check_orphans_when_profile_and_resume_exist`). The file already imports `list_resumes`? It does not — add `list_resumes` to the existing `from callback.repository.resumes import save_resume` line.

```python
    def test_reonboard_with_existing_profile_replaces_resume(self, tmp_path, monkeypatch):
        monkeypatch.setenv("XDG_DATA_HOME", str(tmp_path))
        monkeypatch.setattr(wiki_module, "BASE_DIR", tmp_path / "profile-wiki")
        _save_profile_with_resumes(tmp_path)
        new_resume = tmp_path / "new.txt"
        new_resume.write_text(
            "John Roe\njohn@example.com\n\nSkills\nRust\n", encoding="utf-8"
        )
        graph = _tmp_graph(tmp_path)
        config = make_config("s-reonboard-1")

        result = graph.invoke(_make_state("s-reonboard-1", resume_path=str(new_resume)), config)

        actual = {
            "resume_label": result.get("resume_label"),
            "intake_status": (result.get("intake") or {}).get("status"),
            "registered": list_resumes(),
        }
        expected = {
            "resume_label": "primary",
            "intake_status": "onboarded",
            "registered": ["primary"],
        }
        assert actual == expected

    def test_reonboard_with_orphans_does_not_enter_create_story(self, tmp_path, monkeypatch):
        monkeypatch.setenv("XDG_DATA_HOME", str(tmp_path))
        monkeypatch.setattr(wiki_module, "BASE_DIR", tmp_path / "profile-wiki")
        _save_profile_with_resumes(tmp_path, orphans=["Rust"])
        new_resume = _resume_txt(tmp_path)
        graph = _tmp_graph(tmp_path)
        config = make_config("s-reonboard-2")

        result = graph.invoke(_make_state("s-reonboard-2", resume_path=str(new_resume)), config)

        assert {k: result.get(k) for k in ("current_story_target", "compiled_profile")} == {
            "current_story_target": None,
            "compiled_profile": None,
        }
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `uv run pytest tests/test_profile_graph.py -q -k reonboard`
Expected: first test FAIL (`registered` is `["backend"]`, `resume_label` is `None`); second test FAIL with an exception from `create_story` (no story intake) or a non-None `current_story_target`.

- [ ] **Step 3: Route on `resume_path`**

In `callback/profile_graph.py` replace `_route_check_profile`:

```python
def _route_check_profile(state: ProfileState) -> str:
    """Route to onboard when a resume is supplied or no profile exists."""
    if state.resume_path or not state.profile_exists:
        return "onboard"
    return "check_orphans"
```

Update the module docstring line `Graph shape: check_profile router → onboard | compile_profile → check_orphans` is fine as is; do not touch the rest.

- [ ] **Step 4: Run the profile graph tests**

Run: `uv run pytest tests/test_profile_graph.py tests/test_profile_integration.py tests/test_server_profile.py -q`
Expected: all PASS.

- [ ] **Step 5: Run the full gate**

Run: `uv run pytest -q && uv run ruff check . && uv run ruff format --check . && uv run pyright`
Expected: all green.

- [ ] **Step 6: Commit**

```bash
git add callback/profile_graph.py tests/test_profile_graph.py
git commit -m "fix(profile): re-onboarding replaces the stored resume

check_profile routed an existing profile straight to check_orphans, so a
second onboard_user call never reached the onboard node: it crashed in
create_story when orphans existed and silently no-oped otherwise. A call
that carries resume_path now always runs onboard.

Closes D2 in INTENT.md.

Co-Authored-By: Claude Fable 5.1 <noreply@anthropic.com>
Claude-Session: https://claude.ai/code/session_01CBmQfLDXe6dxY5JVQnvHcz"
```

---

### Task 3: D3 — One log line per event in `server.log`

**Files:**
- Modify: `callback/server.py:108-136` (`_write_log_line`, `_log`, `_log_exception`)
- Test: `tests/test_server.py` (remove one `patch.object(server, "_write_log_line")` at line 176; add one test)

**Interfaces:**
- Consumes: `configure_logging(log_path)` which installs a `logging.FileHandler` on the root logger tagged with `_callback_log_path`.
- Produces: `_log` and `_log_exception` emit through the `logging` module only. `_write_log_line` is deleted. `_LOG_PATH` stays (used by `run()` and the CLI).

Background: `_log` writes the JSON line straight to the file with `_write_log_line`, then calls `logger.info(line)`, and the root logger's `FileHandler` (installed by `configure_logging`) writes the same line again. `_log_exception` does the same. Deleting the direct write leaves exactly one path to the file.

- [ ] **Step 1: Write the failing test in `tests/test_server.py`**

Append near `test_configure_logging_writes_server_log` (around line 340). Check that existing test first for how it cleans up handlers, and mirror it.

```python
def test_log_writes_one_line_per_event(tmp_path):
    import logging

    import callback.server as server

    log_path = tmp_path / "server.log"
    server.configure_logging(log_path)
    try:
        server._log("INFO", {"event": "dedupe_probe"})
        for handler in logging.getLogger().handlers:
            handler.flush()
        lines = [
            line for line in log_path.read_text(encoding="utf-8").splitlines() if "dedupe_probe" in line
        ]
        assert len(lines) == 1
    finally:
        root = logging.getLogger()
        for handler in list(root.handlers):
            if getattr(handler, "_callback_log_path", None) == str(log_path):
                root.removeHandler(handler)
                handler.close()
```

- [ ] **Step 2: Run the test to verify it fails**

Run: `uv run pytest tests/test_server.py::test_log_writes_one_line_per_event -q`
Expected: FAIL with `assert 2 == 1`.

- [ ] **Step 3: Delete `_write_log_line` and its two call sites**

In `callback/server.py` delete the whole `_write_log_line` function (lines 108-119) and change `_log` / `_log_exception` to:

```python
def _log(level: str, payload: dict) -> None:
    """Log a structured JSON message."""
    payload["timestamp"] = datetime.datetime.now(datetime.UTC).isoformat()
    payload["level"] = level
    logger.info(json.dumps(payload))


def _log_exception(payload: dict) -> None:
    """Log an exception payload plus traceback to stderr and the server log file."""
    payload["traceback"] = traceback.format_exc()
    logger.exception(json.dumps(payload))
```

Then in `tests/test_server.py::test_run_logs_crash_traceback_before_raising` delete the line `patch.object(server, "_write_log_line"),` (the attribute no longer exists and `patch.object` would raise `AttributeError`).

Grep to confirm nothing else references it: `grep -rn "_write_log_line" callback tests` must return nothing.

- [ ] **Step 4: Run the server tests**

Run: `uv run pytest tests/test_server.py tests/test_cli.py -q`
Expected: all PASS.

- [ ] **Step 5: Run the full gate**

Run: `uv run pytest -q && uv run ruff check . && uv run ruff format --check . && uv run pyright`
Expected: all green.

- [ ] **Step 6: Commit**

```bash
git add callback/server.py tests/test_server.py
git commit -m "fix(server): write each log event once

_log and _log_exception wrote the line directly to server.log and then
emitted it through logging, whose FileHandler wrote it again. Drop the
direct write; logging owns the file.

Closes D3 in INTENT.md.

Co-Authored-By: Claude Fable 5.1 <noreply@anthropic.com>
Claude-Session: https://claude.ai/code/session_01CBmQfLDXe6dxY5JVQnvHcz"
```

---

### Task 4: D6 — A bare year range is not a phone number

**Files:**
- Modify: `callback/extractor.py:287-293` (`_extract_phone_candidate`)
- Test: `tests/test_extractor.py` (class `TestContactInfoParsing`)

**Interfaces:**
- Consumes: `_PHONE_RE` (exists), `_parse_contact_info(lines) -> ContactInfo` (exists, tested at `tests/test_extractor.py:63`).
- Produces: `_extract_phone_candidate(stripped) -> str | None` returns `None` when the candidate's digits are exactly two four-digit years (19xx/20xx).

Background: `_PHONE_RE` matches `2019 - 2023` (8 digits, spaces and a hyphen) and the 7-digit floor accepts it, so a header line like `Senior Engineer, 2019 - 2023` becomes the phone number. Two adjacent years are never a phone number.

- [ ] **Step 1: Write the failing tests in `tests/test_extractor.py`**

Add inside `TestContactInfoParsing` after `test_phone_extracted`:

```python
    def test_year_range_is_not_phone(self):
        lines = [
            "Jane Smith",
            "Senior Engineer, 2019 - 2023",
            "jane.smith@example.com",
        ]
        assert _parse_contact_info(lines) == ContactInfo(
            name="Jane Smith",
            email="jane.smith@example.com",
        )

    def test_dotted_year_range_is_not_phone(self):
        lines = [
            "Jane Smith",
            "2018.2022",
            "jane.smith@example.com",
        ]
        assert _parse_contact_info(lines) == ContactInfo(
            name="Jane Smith",
            email="jane.smith@example.com",
        )
```

If `ContactInfo` has other fields with non-None defaults, run the existing `test_phone_extracted` shape and match it; the expected object must be built the same way that test builds it.

- [ ] **Step 2: Run tests to verify they fail**

Run: `uv run pytest tests/test_extractor.py -q -k year_range`
Expected: 2 FAIL — `phone='2019 - 2023'` / `phone='2018.2022'` present in actual.

- [ ] **Step 3: Reject two-year candidates**

In `callback/extractor.py`, add after `_URL_RE`:

```python
_YEAR_PAIR_RE = re.compile(r"(?:19|20)\d{2}(?:19|20)\d{2}")
```

and replace `_extract_phone_candidate`:

```python
def _extract_phone_candidate(stripped: str) -> str | None:
    """Return phone string if a valid candidate is found, else None."""
    ph = _PHONE_RE.search(stripped)
    if not ph:
        return None
    candidate = ph.group(0).strip()
    digits = re.sub(r"\D", "", candidate)
    if len(digits) < 7 or _YEAR_PAIR_RE.fullmatch(digits):
        return None
    return candidate
```

- [ ] **Step 4: Run the extractor tests**

Run: `uv run pytest tests/test_extractor.py tests/test_extractor_sections.py -q`
Expected: all PASS.

- [ ] **Step 5: Run the full gate**

Run: `uv run pytest -q && uv run ruff check . && uv run ruff format --check . && uv run pyright`
Expected: all green.

- [ ] **Step 6: Commit**

```bash
git add callback/extractor.py tests/test_extractor.py
git commit -m "fix(extractor): do not read a year range as a phone number

A header line such as '2019 - 2023' matched the phone pattern and its
eight digits cleared the seven-digit floor. Reject candidates whose
digits are exactly two four-digit years.

Closes D6 in INTENT.md.

Co-Authored-By: Claude Fable 5.1 <noreply@anthropic.com>
Claude-Session: https://claude.ai/code/session_01CBmQfLDXe6dxY5JVQnvHcz"
```

---

### Task 5: D7 — Extractor errors return an envelope from `submit_keywords` and `submit_tailor`

**Files:**
- Modify: `callback/server.py` — `_submit_keywords_impl` (graph invoke block around line 873-882) and `_apply_tailor_edits` plus the `no_coverage` branch of `_submit_tailor_impl` (the two `invoke_graph_without_native_tracing(graph, None, config)` calls around lines 1010 and 1088)
- Test: `tests/test_server.py`, `tests/test_submit_tailor.py`

**Interfaces:**
- Consumes: `_log_exception(payload)` and `_err(...)` (exist); `load_jd`'s `except Exception` block at `server.py:685-699` is the pattern to copy.
- Produces: a module-level helper in `server.py`:

```python
def _unexpected_error(stage: str, session_id: str) -> str:
    """Log the active exception with traceback and return an unexpected_error envelope."""
    _log_exception({"tool": stage, "session_id": session_id, "event": "unexpected_error"})
    return _err(
        stage=stage,
        code="unexpected_error",
        message=f"unexpected {stage} failure; inspect callback logs",
        session_id=session_id,
        retriable=False,
    )
```

Both tools return `{"stage": "<tool>", "code": "unexpected_error", "message": "unexpected <tool> failure; inspect callback logs", "retriable": false}` when the graph raises anything not already handled.

Background: `parse_initial` (apply_nodes.py:280) and `parse_final` (apply_nodes.py:550) call `resume_extractor.extract`, which raises `RuntimeError` ("PDF yielded no text"), `ValueError` (unsupported format, too large), or `FileNotFoundError`. `submit_keywords` only catches `ValueError` and mislabels it `invalid_session`; `submit_tailor` catches nothing. Anything else surfaces as a raw MCP tool failure with no envelope, no stage, no log entry. `load_jd` already has the right shape: log the traceback, return `unexpected_error`. Do the same here. Keep the existing `except ValueError → invalid_session` clause in `submit_keywords` unchanged (it guards checkpoint errors) and add the catch-all after it.

- [ ] **Step 1: Write the failing test for `submit_keywords` in `tests/test_server.py`**

Append after `test_submit_keywords_rejects_blank_session_with_session_id` (around line 500):

```python
def test_submit_keywords_returns_envelope_when_extractor_raises(tmp_path, monkeypatch):
    from callback.server import load_jd, submit_keywords

    with patch("callback.server.list_resumes", return_value=["resume"]):
        loaded = json.loads(load_jd(jd_raw_text="Python engineer needed"))
    session_id = loaded["session_id"]

    def broken_extract(path):
        raise RuntimeError("extractor: PDF yielded no text")

    monkeypatch.setattr("callback.apply_nodes.resume_extractor.extract", broken_extract)
    with patch("callback.apply_nodes.get_resume", return_value=str(tmp_path / "resume.pdf")):
        result = json.loads(submit_keywords(session_id=session_id, jd_json=PARTIAL_JD_JSON))

    expected = {
        "status": "error",
        "error": {
            "stage": "submit_keywords",
            "code": "unexpected_error",
            "message": "unexpected submit_keywords failure; inspect callback logs",
            "retriable": False,
        },
        "session_id": session_id,
    }
    assert result == expected
```

`parse_initial` imports `get_resume` from `callback.repository.resumes` at module level, so patching `callback.apply_nodes.get_resume` makes it reach the `resume_extractor.extract(resume_path)` line instead of the `resume_not_found` fallback.

- [ ] **Step 2: Run the test to verify it fails**

Run: `uv run pytest tests/test_server.py::test_submit_keywords_returns_envelope_when_extractor_raises -q`
Expected: FAIL — `RuntimeError: extractor: PDF yielded no text` escapes the tool.

- [ ] **Step 3: Add `_unexpected_error` and catch in `_submit_keywords_impl`**

Add the `_unexpected_error` helper (code in Interfaces above) directly below `_err` in `callback/server.py`.

Change the invoke block in `_submit_keywords_impl` from:

```python
    try:
        graph.update_state(config, {"keywords": keywords})
        state = invoke_graph_without_native_tracing(graph, None, config)
    except ValueError as exc:
        return _err(
            stage="submit_keywords",
            code="invalid_session",
            message=str(exc),
            session_id=session_id,
            retriable=False,
        )
```

to:

```python
    try:
        graph.update_state(config, {"keywords": keywords})
        state = invoke_graph_without_native_tracing(graph, None, config)
    except ValueError as exc:
        return _err(
            stage="submit_keywords",
            code="invalid_session",
            message=str(exc),
            session_id=session_id,
            retriable=False,
        )
    except Exception:
        return _unexpected_error("submit_keywords", session_id)
```

- [ ] **Step 4: Run the test to verify it passes**

Run: `uv run pytest tests/test_server.py -q -k "submit_keywords"`
Expected: all PASS.

- [ ] **Step 5: Write the failing test for `submit_tailor` in `tests/test_submit_tailor.py`**

The file has an autouse `fake_pdf_renderer` fixture that patches `callback.apply_nodes.resume_extractor.extract` with `fake_extract`. This test overrides that patch after the fixture ran. Read `_run_to_tailor` (line ~105-140) to see its full signature and reuse it. Append:

```python
def test_submit_tailor_returns_envelope_when_extractor_raises(tmp_path, monkeypatch):
    from callback.server import submit_tailor

    resume_label = "test_resume"
    monkeypatch.setattr("callback.wiki.BASE_DIR", tmp_path / "wiki")
    _make_section_map_and_write(resume_label)
    jd_json = json.dumps({"title": "SWE", "company": "Co", "required": ["Python"]})
    session_id = _run_to_tailor(tmp_path, jd_json, resume_label, monkeypatch)

    def broken_extract(path):
        raise RuntimeError("extractor: PDF yielded no text")

    monkeypatch.setattr("callback.apply_nodes.resume_extractor.extract", broken_extract)

    result = json.loads(submit_tailor(session_id=session_id, edits=[]))

    expected = {
        "status": "error",
        "error": {
            "stage": "submit_tailor",
            "code": "unexpected_error",
            "message": "unexpected submit_tailor failure; inspect callback logs",
            "retriable": False,
        },
        "session_id": session_id,
    }
    assert result == expected
```

`_make_section_map_and_write` and `_run_to_tailor` are existing helpers in that file (lines ~80-125); `test_submit_tailor_applies_valid_edits_and_rescores` shows the same setup.

- [ ] **Step 6: Run the test to verify it fails**

Run: `uv run pytest tests/test_submit_tailor.py::test_submit_tailor_returns_envelope_when_extractor_raises -q`
Expected: FAIL — `RuntimeError` escapes.

- [ ] **Step 7: Catch in both `submit_tailor` invoke sites**

In `_submit_tailor_impl` `no_coverage` branch, change:

```python
        graph.update_state(config, {"no_coverage": True, "output_dir": resolved_output_dir})
        invoke_graph_without_native_tracing(graph, None, config)
```

to:

```python
        graph.update_state(config, {"no_coverage": True, "output_dir": resolved_output_dir})
        try:
            invoke_graph_without_native_tracing(graph, None, config)
        except Exception:
            return _unexpected_error("submit_tailor", session_id)
```

In `_apply_tailor_edits`, change:

```python
    invoke_graph_without_native_tracing(graph, None, config)

    final_snapshot = graph.get_state(config)
```

to:

```python
    try:
        invoke_graph_without_native_tracing(graph, None, config)
    except Exception:
        return _unexpected_error("submit_tailor", session_id)

    final_snapshot = graph.get_state(config)
```

If ruff C901 flags `_submit_tailor_impl` after this change, move the `no_coverage` branch body into a helper `_submit_tailor_no_coverage(session_id, graph, config, resolved_output_dir) -> str` and call it; do not restructure anything else.

- [ ] **Step 8: Run both test files**

Run: `uv run pytest tests/test_server.py tests/test_submit_tailor.py -q`
Expected: all PASS.

- [ ] **Step 9: Run the full gate**

Run: `uv run pytest -q && uv run ruff check . && uv run ruff format --check . && uv run pyright`
Expected: all green.

- [ ] **Step 10: Commit**

```bash
git add callback/server.py tests/test_server.py tests/test_submit_tailor.py
git commit -m "fix(server): return an envelope when the graph raises in apply tools

submit_keywords and submit_tailor let extractor errors (empty PDF,
unsupported format) escape as raw MCP failures. Both now log the
traceback and return unexpected_error, matching load_jd.

Closes D7 in INTENT.md.

Co-Authored-By: Claude Fable 5.1 <noreply@anthropic.com>
Claude-Session: https://claude.ai/code/session_01CBmQfLDXe6dxY5JVQnvHcz"
```

---

### Task 6: Record M1 as shipped in `INTENT.md`

**Files:**
- Modify: `INTENT.md` (defect table rows D1, D2, D3, D6, D7; the M1 heading)

- [ ] **Step 1: Mark the rows**

In the "Known defects" table, change the Severity cell of D1, D2, D3, D6, D7 to `Fixed (M1)`. Leave D4, D5, D8 as they are. Under `### M1 — Close the trust boundary (half a day)` change the `Ships:` line to `Shipped 2026-09-03: D1, D2, D3, D6, D7.`

- [ ] **Step 2: Commit**

```bash
git add INTENT.md
git commit -m "docs(intent): mark M1 defects shipped

Co-Authored-By: Claude Fable 5.1 <noreply@anthropic.com>
Claude-Session: https://claude.ai/code/session_01CBmQfLDXe6dxY5JVQnvHcz"
```
