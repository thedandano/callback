# M2 — Make the Graphs Honest: Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Ship W12, D4, and the graph half of W2 from `INTENT.md`: build each LangGraph once per process, let a failed render leave the apply session waiting at the tailor interrupt so `submit_tailor` can be retried, and make `compile_profile` / `create_story` resume the checkpointed profile graph so the `check_orphans → create_story → compile_profile` cycle actually runs.

**Architecture:** Two cached accessors (`get_apply_graph`, `get_profile_graph`) sit beside the existing builders; the builders stay pure so tests can pass their own DB path. The apply graph's error routers send `tailor`/`render`/`parse_final` failures back to `tailor` (already an `interrupt_before` node) instead of `END`, and `submit_tailor` clears `error` on retry. The profile graph pauses before `create_story` instead of after `compile_profile`; `compile_profile` and `create_story` accept an optional `session_id` to resume a thread and start a new one otherwise.

**Tech Stack:** Python 3.12, LangGraph (`StateGraph`, `SqliteSaver`, `interrupt_before` / `interrupt_after`, `update_state`), FastMCP, pytest.

**Spec:** `INTENT.md` §"M2 — Make the graphs honest", plus operating principles 3 (no silent failures) and 5 (lazy by default). `DECISIONS.md` Q1 (keep the profile graph and make it real).

## Global Constraints

- Tests assert whole objects: `assert actual == expected` on the full dict/model. No piecemeal key checks.
- ruff: line length 100, `max-complexity = 7`. `uv run ruff check .` and `uv run ruff format --check .` clean.
- `uv run pyright` 0 errors. `uv run pytest -q` green at every commit (617 at branch start).
- No silent failures: every skipped or swallowed condition is logged through `_log` in `server.py`.
- Envelopes only: every MCP tool returns via `_ok` / `_err`. No raw exceptions escape a tool.
- Do not touch tailor instructions, extraction protocol, or scoring.
- Trust boundary: any host-supplied `session_id` that names no thread returns `session_not_found`; a thread not waiting where the tool expects returns `invalid_state`.
- Commit trailer on every commit:
  ```
  Co-Authored-By: Claude Fable 5.1 <noreply@anthropic.com>
  Claude-Session: https://claude.ai/code/session_01CBmQfLDXe6dxY5JVQnvHcz
  ```

## File Structure

| File | Change |
|------|--------|
| `callback/apply_graph.py` | add `get_apply_graph()` (cached); replace `_route_or_halt` with `_route_or_retry`; `_tailor_route` error → `TAILOR_NODE` |
| `callback/profile_graph.py` | add `get_profile_graph()` (cached); router `check_profile` gains `compile_profile` and `create_story` targets; interrupts become `after=["onboard"]`, `before=["create_story"]` |
| `callback/server.py` | call the cached accessors; `submit_tailor` clears `error` on retry and returns `retriable=True` pipeline errors; `compile_profile` / `create_story` run the profile graph with optional `session_id` |
| `tests/test_apply_graph.py`, `tests/test_submit_tailor.py` | singleton and render-retry tests |
| `tests/test_profile_graph.py`, `tests/test_server_profile.py`, `tests/test_server.py`, `tests/test_profile_integration.py` | new interrupt shape, graph-backed tool tests, patch-target renames |
| `CLAUDE.md`, `AGENTS.md`, `INTENT.md`, `skills/onboard-profile/SKILL.md` | document the new shape; mark D4 / W12 / W2-graph shipped |

---

### Task 1: Build each graph once per process (W12)

**Files:**
- Modify: `callback/apply_graph.py` (after `build_apply_graph`)
- Modify: `callback/profile_graph.py` (after `build_profile_graph`)
- Modify: `callback/server.py` call sites at lines ~655, ~900, ~1052, ~1273, ~1472
- Modify: `tests/test_server.py`, `tests/test_server_profile.py`, `tests/test_profile_integration.py` (patch targets)
- Test: `tests/test_apply_graph.py`, `tests/test_profile_graph.py`

**Interfaces:**
- Produces: `apply_graph.get_apply_graph() -> CompiledStateGraph` and `profile_graph.get_profile_graph() -> CompiledStateGraph`, both `functools.cache`d zero-arg wrappers around the existing builders with the default `DB_PATH`. Later tasks and all of `server.py` use only these.
- The `tests/conftest.py` autouse fixture pops `callback.server`, `callback.apply_graph`, `callback.profile_graph` from `sys.modules` per test, which resets the cache; do not add a manual reset hook.

- [ ] **Step 1: Write the failing tests**

`tests/test_apply_graph.py`:
```python
def test_get_apply_graph_returns_the_same_instance():
    from callback.apply_graph import get_apply_graph

    assert get_apply_graph() is get_apply_graph()
```
`tests/test_profile_graph.py` (module level, next to `_tmp_graph`):
```python
def test_get_profile_graph_returns_the_same_instance():
    from callback.profile_graph import get_profile_graph

    assert get_profile_graph() is get_profile_graph()
```

- [ ] **Step 2: Run them, expect ImportError**

Run: `uv run pytest tests/test_apply_graph.py::test_get_apply_graph_returns_the_same_instance tests/test_profile_graph.py::test_get_profile_graph_returns_the_same_instance -v`

- [ ] **Step 3: Add the accessors**

`callback/apply_graph.py`, after `build_apply_graph`:
```python
@functools.cache
def get_apply_graph():
    """Return the process-wide apply graph, built on first use."""
    return build_apply_graph()
```
Same in `callback/profile_graph.py` as `get_profile_graph`. Add `import functools` to both.

- [ ] **Step 4: Switch server.py to the accessors**

Replace every `build_apply_graph()` call in `server.py` with `get_apply_graph()` and the one `build_profile_graph()` call with `get_profile_graph()`. Update the imports so `server.py` no longer imports the builders.

- [ ] **Step 5: Rename the test patch targets**

Every `patch("callback.server.build_apply_graph", ...)`, `patch.object(server, "build_apply_graph", ...)`, and `monkeypatch.setattr(server_module, "build_profile_graph", ...)` in `tests/test_server.py`, `tests/test_server_profile.py`, `tests/test_profile_integration.py` becomes the `get_*` name. Tests that call `build_apply_graph()` directly to inspect state (e.g. `tests/test_server.py:1413-1485`, `tests/test_apply_e2e.py`) keep working because they share the same default `DB_PATH`, but they must read state through `get_apply_graph()` so they see the server's connection. Change those to `get_apply_graph()`.

- [ ] **Step 6: Full verification**

Run: `uv run pytest -q && uv run ruff check . && uv run ruff format --check . && uv run pyright`

- [ ] **Step 7: Commit**

```
perf(graphs): build each graph once per process
```

---

### Task 2: A failed render leaves the session at the tailor interrupt (D4)

**Files:**
- Modify: `callback/apply_graph.py` (`_route_or_halt`, `_tailor_route`, edge wiring)
- Modify: `callback/server.py` (`_apply_tailor_edits`, `_submit_tailor_no_coverage`)
- Test: `tests/test_submit_tailor.py`, `tests/test_apply_graph.py`

**Interfaces:**
- Consumes: `get_apply_graph()` from Task 1.
- Produces: after any error in `tailor`, `render`, or `parse_final`, `graph.get_state(config).next == (TAILOR_NODE,)` and `state.error` holds the message. `submit_tailor` returns `pipeline_error` with `retriable: true` and a retry with the same `session_id` runs the pipeline again.

Background: `render_resume` already converts Playwright failures into `{"success": False, "error": ...}`, and the `render` node returns `{"error": ...}`. Today `_route_or_halt` sends that to `END`, so `snapshot.next` is `()` and a retry gets `invalid_state`. The fix is routing, not exception handling.

- [ ] **Step 1: Write the failing tests**

`tests/test_submit_tailor.py` (the autouse `fake_pdf_renderer` fixture always succeeds; override it inside the test):
```python
def test_submit_tailor_can_be_retried_after_render_failure(tmp_path, monkeypatch):
    from callback.server import submit_tailor

    session_id = _run_to_tailor(tmp_path, _JD_JSON, monkeypatch=monkeypatch)
    calls = {"n": 0}
    real_render = callback.apply_nodes.render_resume

    def flaky_render(tailored, output_path):
        calls["n"] += 1
        if calls["n"] == 1:
            return {"success": False, "error": "chromium crashed"}
        return real_render(tailored, output_path)

    monkeypatch.setattr("callback.apply_nodes.render_resume", flaky_render)

    first = json.loads(submit_tailor(session_id=session_id, edits=[]))
    assert first == {
        "status": "error",
        "error": {
            "stage": "submit_tailor",
            "code": "pipeline_error",
            "message": "render: chromium crashed",
            "retriable": True,
        },
        "session_id": session_id,
    }

    second = json.loads(submit_tailor(session_id=session_id, edits=[]))
    assert {"status": second["status"], "pdf_exists": Path(second["data"]["pdf_path"]).exists()} == {
        "status": "ok",
        "pdf_exists": True,
    }
```
Use the same `_JD_JSON` (or whatever the file names its JD fixture string) and edits shape that `test_submit_tailor_applies_valid_edits_and_rescores` uses so the pipeline reaches `render`.

`tests/test_apply_graph.py`:
```python
def test_render_error_routes_back_to_tailor():
    from callback.apply_graph import TAILOR_NODE, _route_or_retry
    from callback.state import ApplyState

    router = _route_or_retry("parse_final")
    assert router(ApplyState(session_id="s", error="render: boom")) == TAILOR_NODE
    assert router(ApplyState(session_id="s")) == "parse_final"
```

- [ ] **Step 2: Run them, expect failure**

Run: `uv run pytest tests/test_submit_tailor.py::test_submit_tailor_can_be_retried_after_render_failure tests/test_apply_graph.py::test_render_error_routes_back_to_tailor -v`
Expected: first fails on `invalid_state` for the second call; second fails with ImportError.

- [ ] **Step 3: Reroute errors to tailor**

`callback/apply_graph.py`:
```python
def _route_or_retry(next_node: str):
    """Route to next_node, or back to the tailor interrupt when the state carries an error."""

    def _router(state: ApplyState) -> str:
        return TAILOR_NODE if state.error else next_node

    return _router


def _tailor_route(state: ApplyState) -> str:
    if state.error:
        return TAILOR_NODE
    if state.no_coverage:
        return REPORT_NODE
    return RENDER_NODE
```
Replace both `_route_or_halt(...)` usages with `_route_or_retry(...)`. Delete `_route_or_halt`. Move the `*_NODE` constants above the routers if needed so `TAILOR_NODE` is defined first.

- [ ] **Step 4: Clear the error on retry and mark the envelope retriable**

`callback/server.py`, in `_apply_tailor_edits` and `_submit_tailor_no_coverage`, add `"error": None` to the dict passed to `graph.update_state(...)`. In both places where `final.get("error")` produces `_err("submit_tailor", "pipeline_error", ...)`, pass `retriable=True`. Log the retry: before `update_state`, if `snapshot.values.get("error")`, call `_log("INFO", {"tool": "submit_tailor", "session_id": session_id, "event": "retry_after_error"})`. If that pushes a function over C901 = 7, extract `_tailor_retry_update(graph, config, values: dict, session_id) -> None` that does the log plus `update_state`.

- [ ] **Step 5: Run the two tests, then the full suite**

Run: `uv run pytest -q && uv run ruff check . && uv run ruff format --check . && uv run pyright`

Existing tests that assert an error ends the graph (grep `tests/test_apply_graph.py` and `tests/test_apply_e2e.py` for `error` and `.next`) must be updated to expect `next == ("tailor",)` instead of `()`. Update the expectation; do not delete the test.

- [ ] **Step 6: Commit**

```
fix(apply): route render failures back to the tailor interrupt
```

---

### Task 3: Profile graph pauses before create_story, compile flows into check_orphans

**Files:**
- Modify: `callback/profile_graph.py` (`_route_check_profile`, conditional edge map, `interrupt_*`, module docstring)
- Test: `tests/test_profile_graph.py`

**Interfaces:**
- Consumes: nothing new.
- Produces: graph compiled with `interrupt_after=["onboard"]`, `interrupt_before=["create_story"]`. Router `_route_check_profile(state) -> "onboard" | "create_story" | "compile_profile"`. Helper `story_pending(intake: dict | None) -> bool` (public, used by Task 4): True when `intake` has a `primary_skill` and no `story_id`.

New shape:
```
check_profile ──(resume_path or no profile)──▶ onboard ─▶ compile_profile ─▶ check_orphans
              ├─(story pending in intake)────▶ create_story ─▶ compile_profile ─┘   │
              └─(otherwise)──────────────────▶ compile_profile ─────────────────┘   │
                                                                                     ▼
                              create_story ◀──(orphans)── check_orphans ──(none)──▶ END
Interrupts: after onboard; before create_story.
```

- [ ] **Step 1: Write the failing tests**

In `tests/test_profile_graph.py` replace `TestInterruptAfterCompileProfile` with:
```python
class TestCompileFlowsIntoCheckOrphans:
    def test_compile_profile_runs_through_to_check_orphans(self, tmp_path, monkeypatch):
        monkeypatch.setenv("XDG_DATA_HOME", str(tmp_path))
        monkeypatch.setattr(wiki_module, "BASE_DIR", tmp_path / "profile-wiki")
        _save_profile_with_resumes(tmp_path)
        graph = _tmp_graph(tmp_path)
        config = make_config("s-cp-1")

        result = graph.invoke(_make_state("s-cp-1"), config)

        assert {
            "has_compiled_profile": result.get("compiled_profile") is not None,
            "orphaned_skills": result.get("orphaned_skills"),
            "next": graph.get_state(config).next,
        } == {"has_compiled_profile": True, "orphaned_skills": [], "next": ()}

    def test_orphans_pause_before_create_story(self, tmp_path, monkeypatch):
        monkeypatch.setenv("XDG_DATA_HOME", str(tmp_path))
        monkeypatch.setattr(wiki_module, "BASE_DIR", tmp_path / "profile-wiki")
        _save_profile_with_resumes(tmp_path, orphans=["Rust"])
        graph = _tmp_graph(tmp_path)
        config = make_config("s-cp-2")

        graph.invoke(_make_state("s-cp-2"), config)

        assert graph.get_state(config).next == ("create_story",)
```
Note: `compile_profile` recompiles from stored stories, so `orphaned_skills` after a compile reflects the recompiled profile, not the seeded one. If the seeded orphan list does not survive `ProfileCompiler().compile(...)` with zero stories, seed a story whose tags leave `Rust` orphaned instead (see how `tests/test_profilecompiler.py` builds orphans) and keep the assertion on `next`.

Replace `TestInterruptAfterCreateStory.test_graph_pauses_after_create_story_when_orphan_exists` with:
```python
class TestCreateStoryInterrupt:
    def test_pending_story_on_new_thread_pauses_before_create_story(self, tmp_path, monkeypatch):
        monkeypatch.setenv("XDG_DATA_HOME", str(tmp_path))
        monkeypatch.setattr(wiki_module, "BASE_DIR", tmp_path / "profile-wiki")
        _save_profile_with_resumes(tmp_path)
        graph = _tmp_graph(tmp_path)
        config = make_config("s-create-1")
        intake = {"primary_skill": "Rust", "skills": ["Rust"], "story_type": "STAR",
                  "job_title": "Systems Engineer", "situation": "S", "behavior": "B", "impact": "I"}

        graph.invoke(_make_state("s-create-1", intake=intake), config)

        assert graph.get_state(config).next == ("create_story",)

    def test_resuming_runs_create_story_then_compile_then_check_orphans(self, tmp_path, monkeypatch):
        monkeypatch.setenv("XDG_DATA_HOME", str(tmp_path))
        monkeypatch.setattr(wiki_module, "BASE_DIR", tmp_path / "profile-wiki")
        _save_profile_with_resumes(tmp_path)
        graph = _tmp_graph(tmp_path)
        config = make_config("s-create-2")
        intake = {"primary_skill": "Rust", "skills": ["Rust"], "story_type": "STAR",
                  "job_title": "Systems Engineer", "situation": "S", "behavior": "B", "impact": "I"}
        graph.invoke(_make_state("s-create-2", intake=intake), config)

        result = graph.invoke(None, config)

        assert {
            "story_saved": bool((result.get("intake") or {}).get("story_id")),
            "has_compiled_profile": result.get("compiled_profile") is not None,
            "orphaned_skills": result.get("orphaned_skills"),
            "next": graph.get_state(config).next,
        } == {"story_saved": True, "has_compiled_profile": True, "orphaned_skills": [], "next": ()}
```
Add to `TestCheckProfileRouter`:
```python
    def test_routes_to_compile_profile_when_profile_exists_and_no_resume_path(self):
        state = ProfileState(session_id="s", profile_exists=True)
        assert _route_check_profile(state) == "compile_profile"

    def test_routes_to_create_story_when_story_pending(self):
        state = ProfileState(session_id="s", profile_exists=True, intake={"primary_skill": "Rust"})
        assert _route_check_profile(state) == "create_story"

    def test_saved_story_is_not_pending(self):
        state = ProfileState(
            session_id="s", profile_exists=True, intake={"primary_skill": "Rust", "story_id": "story-001"}
        )
        assert _route_check_profile(state) == "compile_profile"
```
Rename `test_routes_to_check_orphans_when_profile_and_resume_exist` to `test_routes_to_compile_profile_when_profile_and_resume_exist` and change its expected value to `"compile_profile"`. `test_reonboard_with_orphans_does_not_enter_create_story` still holds (onboard pauses first).

- [ ] **Step 2: Run, expect failures**

Run: `uv run pytest tests/test_profile_graph.py -v`

- [ ] **Step 3: Implement**

`callback/profile_graph.py`:
```python
def story_pending(intake: dict | None) -> bool:
    """True when the host has supplied a story that has not been saved yet."""
    return bool(intake and intake.get("primary_skill") and not intake.get("story_id"))


def _route_check_profile(state: ProfileState) -> str:
    """Onboard when a resume is supplied or no profile exists; else save a pending story or recompile."""
    if state.resume_path or not state.profile_exists:
        return "onboard"
    if story_pending(state.intake):
        return "create_story"
    return "compile_profile"
```
Conditional edge map becomes `{"onboard": "onboard", "create_story": "create_story", "compile_profile": "compile_profile"}`. Compile with `interrupt_after=["onboard"]`, `interrupt_before=["create_story"]`. Update the module docstring to the new shape diagram above.

- [ ] **Step 4: Full verification**

Run: `uv run pytest -q && uv run ruff check . && uv run ruff format --check . && uv run pyright`

`tests/test_profile_integration.py` and `tests/test_server.py` tests around `onboard_user` may assert `next_action` or state after onboarding; onboard's interrupt is unchanged, so they should pass. Anything asserting the graph pauses after `compile_profile` gets updated to the new shape.

- [ ] **Step 5: Commit**

```
refactor(profile-graph): pause before create_story so compile flows into check_orphans
```

---

### Task 4: compile_profile and create_story resume the profile graph

**Files:**
- Modify: `callback/server.py` (`compile_profile`, `create_story` tools; new `_compile_profile_impl`, `_create_story_impl`, `_run_profile_thread`, `_profile_thread_data`)
- Test: `tests/test_server_profile.py` (rewrite `TestCompileProfile`, `TestCreateStory` to run the real graph), `tests/test_server.py`

**Interfaces:**
- Consumes: `get_profile_graph()` (Task 1), `story_pending` and the new interrupt shape (Task 3), `make_profile_config`, `invoke_graph_without_native_tracing`, `_unexpected_error`, `_parse_story_tags`, `_resolve_resume_label`.
- Produces: tool signatures
  - `compile_profile(story_tags: str | None = None, session_id: str | None = None) -> str`
  - `create_story(primary_skill, skills, story_type, job_title, situation, behavior, impact, session_id: str | None = None) -> str`
  - Both return `session_id` of the thread they ran (new or resumed), `next_action = "create_story"` when the thread paused before `create_story`, else `None`, and `data.orphaned_skills` (list). `create_story` data keeps `story_id` and `primary_skill`, and `needs_compile` becomes `False` because compile already ran in the same invoke.

Thread semantics:
- `compile_profile` with `session_id`: the thread must exist and be paused (`next == ("compile_profile",)` after onboard, or `("create_story",)`). Apply `update_state(config, {"compiled_profile": {"host_tags": tags}})` then invoke `None`. A thread paused before `create_story` with no pending story recompiles by `update_state(..., as_node="check_orphans")`? No: keep it simple. If `next == ("create_story",)` and the host calls `compile_profile`, return `invalid_state` with message `"session is waiting for create_story"`. Only `("compile_profile",)` resumes.
- `compile_profile` without `session_id`: new thread, `ProfileState(session_id, resume_label, compiled_profile={"host_tags": tags} if tags else None)`; invoke it. `check_profile` routes to `compile_profile`. If no profile exists the router goes to `onboard`, which returns `intake.status == "no_resume"`; map that to `_err("compile_profile", "profile_missing", "no profile; call onboard_user first", session_id)`.
- `create_story` with `session_id`: thread must have `next == ("create_story",)`; else `invalid_state`. `update_state(config, {"intake": intake})` then invoke `None`.
- `create_story` without `session_id`: new thread with `ProfileState(session_id, intake=intake)`; invoke it. The router sends it to `create_story`, where `interrupt_before` pauses. Because the story is already pending, invoke `None` once more. Encapsulate this in `_run_profile_thread`.
- Any thread that ends with `intake.status == "no_resume"` returns `profile_missing`.

- [ ] **Step 1: Write the failing tests**

Rewrite `tests/test_server_profile.py::TestCompileProfile` and `TestCreateStory` to drive the real graph (the conftest fixture isolates the DB; use `monkeypatch.setenv("XDG_DATA_HOME", str(tmp_path))` and `monkeypatch.setattr(wiki_module, "BASE_DIR", tmp_path / "profile-wiki")` like `tests/test_profile_graph.py`, and seed a profile with `_save_profile_with_resumes`, copied or imported from that file). Keep the four onboard tests untouched.

```python
class TestCompileProfile:
    def test_new_thread_compiles_and_reports_no_orphans(self, tmp_path, monkeypatch):
        _isolate_profile(tmp_path, monkeypatch)
        _save_profile_with_resumes(tmp_path)

        result = json.loads(compile_profile())

        assert {
            "status": result["status"],
            "next_action": result.get("next_action"),
            "orphaned_skills": result["data"]["orphaned_skills"],
            "has_compiled_profile": bool(result["data"]["compiled_profile"]),
            "keys": sorted(result["data"]),
        } == {
            "status": "ok",
            "next_action": None,
            "orphaned_skills": [],
            "has_compiled_profile": True,
            "keys": ["compiled_profile", "orphaned_skills", "skill_coverage_warnings", "skills_index"],
        }

    def test_resumes_onboard_thread(self, tmp_path, monkeypatch):
        _isolate_profile(tmp_path, monkeypatch)
        resume = _resume_txt(tmp_path)
        onboarded = json.loads(onboard_user(resume_path=str(resume)))

        result = json.loads(compile_profile(session_id=onboarded["session_id"]))

        assert {"status": result["status"], "session_id": result["session_id"]} == {
            "status": "ok",
            "session_id": onboarded["session_id"],
        }

    def test_unknown_session_returns_session_not_found(self, tmp_path, monkeypatch):
        _isolate_profile(tmp_path, monkeypatch)

        result = json.loads(compile_profile(session_id="nope"))

        assert result == {
            "status": "error",
            "error": {
                "stage": "compile_profile",
                "code": "session_not_found",
                "message": "session_id not found",
                "retriable": False,
            },
            "session_id": "nope",
        }

    def test_without_profile_returns_profile_missing(self, tmp_path, monkeypatch):
        _isolate_profile(tmp_path, monkeypatch)

        result = json.loads(compile_profile())

        assert result["error"] == {
            "stage": "compile_profile",
            "code": "profile_missing",
            "message": "no profile; call onboard_user first",
            "retriable": False,
        }

    def test_invalid_story_tags_still_rejected(self):
        result = json.loads(compile_profile(story_tags="not json"))
        assert result["error"]["code"] == "invalid_story_tags"
```
```python
class TestCreateStory:
    def test_new_thread_saves_story_and_compiles(self, tmp_path, monkeypatch):
        _isolate_profile(tmp_path, monkeypatch)
        _save_profile_with_resumes(tmp_path)

        result = json.loads(create_story(**_STORY_FIELDS))

        assert {
            "status": result["status"],
            "next_action": result.get("next_action"),
            "story_saved": bool(result["data"]["story_id"]),
            "primary_skill": result["data"]["primary_skill"],
            "needs_compile": result["data"]["needs_compile"],
            "orphaned_skills": result["data"]["orphaned_skills"],
        } == {
            "status": "ok",
            "next_action": None,
            "story_saved": True,
            "primary_skill": "Python",
            "needs_compile": False,
            "orphaned_skills": [],
        }

    def test_resumes_thread_paused_before_create_story(self, tmp_path, monkeypatch):
        _isolate_profile(tmp_path, monkeypatch)
        _save_profile_with_resumes(tmp_path, orphans=["Rust"])  # or seed via a story, see Task 3 note
        compiled = json.loads(compile_profile())
        assert compiled["next_action"] == "create_story"

        result = json.loads(create_story(session_id=compiled["session_id"], **{**_STORY_FIELDS, "primary_skill": "Rust", "skills": ["Rust"]}))

        assert {"status": result["status"], "session_id": result["session_id"], "orphaned_skills": result["data"]["orphaned_skills"]} == {
            "status": "ok",
            "session_id": compiled["session_id"],
            "orphaned_skills": [],
        }

    def test_session_not_waiting_for_story_returns_invalid_state(self, tmp_path, monkeypatch):
        _isolate_profile(tmp_path, monkeypatch)
        _save_profile_with_resumes(tmp_path)
        compiled = json.loads(compile_profile())  # ends, next == ()

        result = json.loads(create_story(session_id=compiled["session_id"], **_STORY_FIELDS))

        assert result["error"] == {
            "stage": "create_story",
            "code": "invalid_state",
            "message": "session is not waiting for create_story",
            "retriable": False,
        }

    def test_node_exception_returns_unexpected_error(self, tmp_path, monkeypatch):
        _isolate_profile(tmp_path, monkeypatch)
        _save_profile_with_resumes(tmp_path)
        monkeypatch.setattr(pnodes.AccomplishmentsStore, "save_story", lambda self, story: (_ for _ in ()).throw(RuntimeError("disk")))

        result = json.loads(create_story(**_STORY_FIELDS))

        assert result["error"]["code"] == "unexpected_error"
```
Define `_isolate_profile(tmp_path, monkeypatch)` at module level in the test file to set `XDG_DATA_HOME` and `wiki_module.BASE_DIR`. Delete `_fake_graph`-based compile/create tests and the `_COMPILE_DELTA` / `_CREATE_DELTA` constants if nothing else uses them. In `tests/test_server.py`, any test asserting the exact `create_story` / `compile_profile` tool signature or `needs_compile: True` is updated to the new contract.

- [ ] **Step 2: Run, expect failures**

Run: `uv run pytest tests/test_server_profile.py -v`

- [ ] **Step 3: Implement the shared thread runner**

`callback/server.py`, near `_onboard_user_invoke`:
```python
def _run_profile_thread(graph, config, graph_input, session_id: str, stage: str):
    """Invoke the profile graph; if it paused before create_story with a story pending, continue once.

    Returns (state_values, error_envelope_or_None).
    """
    try:
        invoke_graph_without_native_tracing(graph, graph_input, config)
        snapshot = graph.get_state(config)
        if snapshot.next == ("create_story",) and story_pending(snapshot.values.get("intake")):
            invoke_graph_without_native_tracing(graph, None, config)
            snapshot = graph.get_state(config)
    except Exception:
        return None, _unexpected_error(stage, session_id)
    values = snapshot.values
    if (values.get("intake") or {}).get("status") == "no_resume":
        return None, _err(stage, "profile_missing", "no profile; call onboard_user first", session_id)
    return values, None


def _profile_thread_data(graph, config, values: dict) -> tuple[str | None, dict]:
    """Return (next_action, common data) for a profile thread after a run."""
    paused = graph.get_state(config).next == ("create_story",)
    intake = values.get("intake") or {}
    data = {
        "compiled_profile": values.get("compiled_profile") or {},
        "skill_coverage_warnings": intake.get("skill_coverage_warnings", []),
        "skills_index": intake.get("skills_index", []),
        "orphaned_skills": values.get("orphaned_skills") or [],
    }
    return ("create_story" if paused else None), data


def _profile_snapshot_or_error(graph, config, session_id: str, stage: str, waiting_for: str):
    """Validate a host-supplied session before resuming it. Returns (snapshot, error_or_None)."""
    snapshot = graph.get_state(config)
    if not snapshot.values:
        return None, _err(stage, "session_not_found", "session_id not found", session_id)
    if snapshot.next != (waiting_for,):
        return None, _err(stage, "invalid_state", f"session is not waiting for {waiting_for}", session_id)
    return snapshot, None
```
Import `story_pending` from `callback.profile_graph`.

- [ ] **Step 4: Rewrite the two tools**

```python
@mcp.tool()
def compile_profile(story_tags: str | None = None, session_id: str | None = None) -> str:
    """Recompile the user profile from all stored stories.

    Args:
        story_tags: Optional JSON string. Accepts a dict (keys become host_tags)
            or a list of skill strings.
        session_id: Optional profile session to resume (from onboard_user). Omit to
            start a new profile session.

    Returns:
        JSON envelope with compiled_profile, skill_coverage_warnings, skills_index,
        and orphaned_skills. next_action is "create_story" when orphans remain.
    """
    resumed = session_id is not None
    session_id = session_id or str(uuid.uuid4())
    _log("INFO", {"tool": "compile_profile", "session_id": session_id, "resumed": resumed,
                  "has_story_tags": story_tags is not None})
    host_tags = _parse_story_tags(story_tags)
    if host_tags is None:
        return _err("compile_profile", "invalid_story_tags",
                    "story_tags must be a JSON dict or list", session_id, retriable=True)
    return _compile_profile_impl(session_id, host_tags, resumed=resumed)


@trace_tool("compile_profile", graph_name="profile")
def _compile_profile_impl(session_id: str, host_tags: list[str], *, resumed: bool) -> str:
    graph = get_profile_graph()
    config = make_profile_config(session_id, tool_name="compile_profile")
    tags = {"host_tags": host_tags} if host_tags else None
    if resumed:
        _, error = _profile_snapshot_or_error(graph, config, session_id, "compile_profile", "compile_profile")
        if error:
            return error
        if tags:
            graph.update_state(config, {"compiled_profile": tags})
        graph_input = None
    else:
        resume_label, _ = _resolve_resume_label(None, session_id)
        graph_input = ProfileState(session_id=session_id, resume_label=resume_label, compiled_profile=tags)
    values, error = _run_profile_thread(graph, config, graph_input, session_id, "compile_profile")
    if error:
        return error
    next_action, data = _profile_thread_data(graph, config, values)
    return _ok(session_id, next_action, data)
```
```python
@mcp.tool()
def create_story(
    primary_skill: str,
    skills: list[str],
    story_type: str,
    job_title: str,
    situation: str,
    behavior: str,
    impact: str,
    session_id: str | None = None,
) -> str:
    """Create and persist a behavioral story for a skill, then recompile the profile.

    Args: (unchanged, plus)
        session_id: Optional profile session paused before create_story (from
            compile_profile or a previous create_story). Omit to start a new session.

    Returns:
        JSON envelope with story_id, primary_skill, needs_compile (always false: the
        profile is recompiled in the same call), and orphaned_skills. next_action is
        "create_story" when orphans remain.
    """
    resumed = session_id is not None
    session_id = session_id or str(uuid.uuid4())
    _log("INFO", {"tool": "create_story", "session_id": session_id, "resumed": resumed,
                  "primary_skill": primary_skill, "story_type": story_type, "job_title": job_title})
    intake = {"primary_skill": primary_skill, "skills": skills, "story_type": story_type,
              "job_title": job_title, "situation": situation, "behavior": behavior, "impact": impact}
    return _create_story_impl(session_id, intake, resumed=resumed)


@trace_tool("create_story", graph_name="profile")
def _create_story_impl(session_id: str, intake: dict, *, resumed: bool) -> str:
    graph = get_profile_graph()
    config = make_profile_config(session_id, tool_name="create_story")
    if resumed:
        _, error = _profile_snapshot_or_error(graph, config, session_id, "create_story", "create_story")
        if error:
            return error
        graph.update_state(config, {"intake": intake})
        graph_input = None
    else:
        graph_input = ProfileState(session_id=session_id, intake=intake)
    values, error = _run_profile_thread(graph, config, graph_input, session_id, "create_story")
    if error:
        return error
    next_action, data = _profile_thread_data(graph, config, values)
    data = {"story_id": (values.get("intake") or {}).get("story_id"),
            "primary_skill": intake["primary_skill"], "needs_compile": False, **data}
    return _ok(session_id, next_action, data)
```
Note on `create_story` resume: `update_state(config, {"intake": intake})` on a thread paused before `create_story` replaces the whole `intake` dict (ProfileState has no reducer), which drops `skill_coverage_warnings` from the prior compile. That is fine: compile runs again in the same invoke and rewrites them.

If ruff C901 trips on either impl, split the resumed/new branch into `_prepare_profile_resume(...)`.

- [ ] **Step 5: Full verification**

Run: `uv run pytest -q && uv run ruff check . && uv run ruff format --check . && uv run pyright`

- [ ] **Step 6: Commit**

```
feat(profile): compile_profile and create_story resume the checkpointed graph
```

---

### Task 5: Documentation

**Files:**
- Modify: `CLAUDE.md` (Architecture → Profile graph diagram, the "Note:" paragraph, tools table rows for `compile_profile` / `create_story`)
- Modify: `AGENTS.md` (same tools table)
- Modify: `INTENT.md` (D4 → `Fixed (M2)`, W12 and W2 rows note the graph half shipped, M2 "Ships:" → "Shipped 2026-09-04: W12, D4, graph half of W2")
- Modify: `skills/onboard-profile/SKILL.md` lines 65-66 and 122: `create_story` now recompiles in the same call and returns `orphaned_skills`; calling `compile_profile()` afterwards is optional. Keep the wording short; do not restructure the skill.

- [ ] **Step 1: Edit the four files**

CLAUDE.md profile graph block becomes:
```
check_profile ──(resume_path or no profile)──▶ onboard ─▶ compile_profile ─▶ check_orphans
              ├─(story pending in intake)────▶ create_story ─▶ compile_profile ─┘   │
              └─(otherwise)──────────────────▶ compile_profile ─────────────────┘   │
                                                                                     ▼
                              create_story ◀──(orphans)── check_orphans ──(none)──▶ END
```
with the sentence: "Interrupts: after `onboard`; before `create_story`. `compile_profile` and `create_story` accept an optional `session_id` to resume the thread; without one they start a new thread that `check_profile` routes to the right node." Delete the old "Note: `onboard_user` enters the profile graph. `compile_profile` and `create_story` still invoke profile nodes directly" paragraph. In the apply graph section add: "Errors in `tailor`, `render`, or `parse_final` route back to the `tailor` interrupt; `submit_tailor` returns `pipeline_error` with `retriable: true` and may be called again with the same session." Under Module map or Architecture add one line: "Both graphs are built once per process via `get_apply_graph()` / `get_profile_graph()`."

- [ ] **Step 2: Verify nothing else references the old names**

Run: `grep -rn "build_apply_graph()\|build_profile_graph()\|_route_or_halt\|interrupt_after=\[\"onboard\", \"compile_profile\"" callback/ CLAUDE.md AGENTS.md`
Expected: no hits in `callback/` except the builder definitions and the `get_*` wrappers.

- [ ] **Step 3: Commit**

```
docs: describe the M2 graph shape and mark D4, W12, W2-graph shipped
```
