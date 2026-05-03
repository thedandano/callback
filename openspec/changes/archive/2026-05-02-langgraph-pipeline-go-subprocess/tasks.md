## 1. Project Bootstrap

- [x] 1.1 Initialize project with `uv init`, add dependencies via `uv add`: `langgraph`, `langchain-core`, `pydantic`, `fastmcp`
- [x] 1.2 Create top-level package structure: `pi_apply/` with `__init__.py`, `state.py`, `graph.py`, `bridge.py`, `server.py`
- [x] 1.3 Add `.env.example` documenting `GO_APPLY_BIN` and `LOG_LEVEL` env vars
- [x] 1.4 In `graph.py` startup, call `Path(db_path).parent.mkdir(parents=True, exist_ok=True)` before `SqliteSaver` opens the file

## 2. Typed State

- [x] 2.1 Implement `ApplyState(BaseModel)` in `state.py` with all fields from the spec (session_id required, all others optional/None); add `edits_t1: list | None` and `edits_t2: list | None` for Claude's edit patches
- [x] 2.2 Write unit tests for `ApplyState` initialization and error-carrying behavior

## 3. Go Subprocess Bridge

- [x] 3.1 Implement `bridge.py` with binary path resolution (env var → PATH → EnvironmentError); resolution runs at module top level
- [x] 3.2 Define `SubprocessError` with `cmd`, `returncode`, `stderr` attributes
- [x] 3.3 Implement `run_pdfrender(args: list[str]) -> bytes` and `run_survival(args: list[str]) -> str`
- [x] 3.4 Write unit tests: (a) resolution failure — use `monkeypatch` on `shutil.which` + `importlib.reload(pi_apply.bridge)` to re-trigger top-level resolution, assert `EnvironmentError` message contains `GO_APPLY_BIN`; (b) successful `run_pdfrender` returns stdout bytes; (c) non-zero exit raises `SubprocessError` with correct `returncode` and `stderr` content

## 4. LangGraph Workflow

- [x] 4.1 Implement `load_jd` node: accept `jd_raw_text` only (URL fetching deferred), populate `jd_text` on state, emit structured log entry
- [x] 4.2 Implement `score` node: score resumes against `keywords`, populate `scored_resumes`, log entry
- [x] 4.3 Implement `tailor_t1` node: apply `edits_t1` patches (injected by caller via `update_state`) to skills section, populate `tailored_t1`, log entry
- [x] 4.4 Implement `tailor_t2` node: apply `edits_t2` patches to experience bullets, populate `tailored_t2`, log entry (PDF render via bridge deferred to post-skeleton)
- [x] 4.5 Implement `finalize` node: persist application record, populate `finalized`, log entry
- [x] 4.6 Wire `StateGraph` in `graph.py`: edges `load_jd → score → tailor_t1 → tailor_t2 → finalize`, compile with `interrupt_after=["load_jd","score","tailor_t1","tailor_t2"]` and `SqliteSaver` pointing to `~/.local/share/pi-apply/sessions.db`; `thread_id = session_id` passed as `RunnableConfig({"configurable": {"thread_id": session_id}})`
- [x] 4.7 Write unit tests: call each node function directly with a constructed `ApplyState` (no checkpointer); assert returned state delta; mock bridge calls via `monkeypatch`; assert ERROR-level log emitted on node exception
- [x] 4.8 Add `PI_APPLY_TEST_STUB=1` env flag: when set, tailor nodes return canned output without LLM calls (inject via callable seam in node functions)
- [x] 4.9 Integration test (SqliteSaver round-trip): compile graph, run `load_jd` node with `tmp_path` SQLite DB, dispose checkpointer object, re-instantiate against same DB path with same `thread_id`, assert second invocation resumes at `score` node — not from `load_jd`
- [x] 4.10 Integration test (full pipeline): with `PI_APPLY_TEST_STUB=1` and a fixture JD + resume, run all five nodes end-to-end, assert `finalized` is non-None

## 5. MCP Server

- [x] 5.1 Scaffold `server.py` with `fastmcp` app; import `bridge` at top level (fail-fast on missing binary); register all twelve tool stubs: `onboard_user`, `add_resume`, `get_config`, `update_config`, `load_jd`, `submit_keywords`, `submit_tailor_t1`, `submit_tailor_t2`, `preview_ats_extraction`, `finalize`, `compile_profile`, `create_story`
- [x] 5.2 Implement `load_jd` tool: validate exclusive jd_url/jd_raw_text, mint UUID as `session_id`, invoke graph (first `invoke` from START), return JSON envelope `{session_id, status:"ok", next_action:"extract_keywords", data:{jd_text}}`
- [x] 5.3 Implement `submit_keywords`: call `graph.update_state(config, {"keywords": parsed_jd_json})` then `graph.invoke(None, config)` (resumes at `score`); return envelope with scores and `next_action:"tailor_t1"`
- [x] 5.4 Implement `submit_tailor_t1`: `update_state(config, {"edits_t1": edits})` then `invoke(None, config)` (resumes at `tailor_t1`); return envelope with `next_action:"tailor_t2"`
- [x] 5.5 Implement `submit_tailor_t2`: `update_state(config, {"edits_t2": edits})` then `invoke(None, config)` (resumes at `tailor_t2`); return envelope
- [x] 5.6 Implement `finalize`: `invoke(None, config)` (resumes at `finalize`); return envelope with `status:"ok"`, no `next_action`
- [x] 5.7 Implement non-workflow tools (bypass graph, no checkpoint write): `onboard_user`, `add_resume`, `get_config`, `update_config`, `compile_profile`, `create_story`, `preview_ats_extraction` — delegate to data/config layer; return plain JSON result
- [x] 5.8 Add structured JSON logging: `timestamp`, `level`, `tool`/`node`, `session_id` per call; full payload at `LOG_LEVEL=DEBUG`
- [x] 5.9 Unit test: import the FastMCP app, enumerate registered tools, assert the set equals exactly the 12 tool names from 5.1
- [x] 5.10 Unit tests (tool routing): exclusive `jd_url`/`jd_raw_text` rejection returns `{status:"error", error:{code:"invalid_input"}}`; unknown `session_id` returns `{status:"error", error:{code:"session_not_found"}}`; `submit_tailor_t1` before `submit_keywords` returns `{status:"error", error:{code:"invalid_state"}}`

## 6. End-to-End Validation

- [x] 6.1 Register pi-apply as MCP server in Claude Code settings
- [x] 6.2 Run the full workflow manually via Claude: onboard resume → load_jd → submit_keywords → submit_tailor_t1 → submit_tailor_t2 → finalize
- [x] 6.3 Verify session persists across a server restart: advance to `score` node, kill server, restart, call `submit_keywords` again, assert it resumes rather than re-running `load_jd`
- [x] 6.4 Confirm node transition logs appear on stderr for each tool call
