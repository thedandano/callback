# pi-apply — Epics & Vertical Slices

Vertical slices ordered by dependency. Each epic delivers a working, testable increment.
Conventional commits required throughout (`feat:`, `fix:`, `chore:`) — release-please reads them.

---

## Epic 0 — Walking Skeleton ✅ COMPLETE

Foundation POC. LangGraph state graph running through the current host keyword handoff, with later parse/score/tailor/render nodes still built out incrementally.

- [x] `uv init`, deps: `langgraph`, `langchain-core`, `pydantic`, `fastmcp`, `fpdf2`
- [x] Package structure: `pi_apply/{__init__, state, apply_graph, apply_nodes, profile_graph, profile_nodes, bridge, server}.py`
- [x] `.env.example` documenting `GO_APPLY_BIN`, `LOG_LEVEL`, `PI_APPLY_TEST_STUB`
- [x] `pyrightconfig.json` for `.venv` type resolution
- [x] `ApplyState(BaseModel)` — typed state with 14 fields covering full pipeline
- [x] `bridge.py` — Go subprocess bridge; fail-fast binary resolution at import time
  - [x] `run_pdfrender(args) -> bytes`
  - [x] `run_survival(args) -> str`
  - [x] `EnvironmentError` on missing binary (no silent degradation)
- [x] `apply_nodes.py` — apply pipeline nodes with structured JSON logging
  - [x] `jd_fetch` — fetches or accepts JD text for host extraction
  - [x] `keywords_accept` — accepts validated host-extracted JDData without inferring keywords
  - [x] Later parse/score/tailor/render/report/finalize nodes remain milestone stubs
- [x] `apply_graph.py` — `StateGraph` compiled with host handoff interrupts + `SqliteSaver`
  - [x] `session_id = thread_id` mapping (no lookup table)
  - [x] `SqliteSaver` at `~/.local/share/pi-apply/apply-sessions.db`
  - [x] `check_same_thread=False` for FastMCP threading
- [x] `server.py` — FastMCP with current MCP tools and consistent JSON envelope
  - [x] `{"session_id", "status", "next_action", "data", "error"}` envelope
  - [x] `load_jd` returns `next_action="extract_keywords"` for host-owned extraction
  - [x] `submit_keywords` stores validated JDData and returns `next_action="parse_initial"`
  - [x] Structured logging (ISO 8601 UTC timestamp + level) on every call
- [x] PDF output via `fpdf2` in `finalize` node (go-apply pdfrender is not a CLI subprocess)
- [x] MCP registered in `~/.claude.json`
- [x] `/apply` slash command at `.claude/commands/apply.md`
- [x] Tests covering the current walking skeleton and handoff surface
  - [x] `test_state.py` (11) — field validation, optional/required
  - [x] `test_bridge.py` (8) — binary resolution, `importlib.reload` pattern
  - [x] `test_nodes.py` (12) — deltas, error logging, `_NotSerializable` ERROR path
  - [x] `test_graph.py` (2) — checkpoint round-trip, full pipeline end-to-end
  - [x] `test_server.py` — MCP tool registration, routing, and handoff envelope behavior
- [x] E2E validated: PlayStation SWE II Data Platform JD — 14/14 skeleton score, 7/14 honest coverage

---

## Epic 0.5 — Host-Handoff Surface ✅ COMPLETE

Shipped after the Epic 0 walking skeleton. Establishes the host-as-brain
pattern that the rest of the graph reuses.

- [x] `jd_data.py` — `JDData` schema, `EXTRACTION_PROTOCOL`, `parse_jd_json` validator
- [x] `jd_fetcher.py` — Crawl4AI-based URL fetch
  - [x] Documented env vars: `PI_APPLY_FETCH_PAGE_TIMEOUT_MS`, `PI_APPLY_FETCH_WAIT_UNTIL`, `PI_APPLY_FETCH_OUTER_TIMEOUT_S`, `PI_APPLY_FETCH_MAGIC`
  - [x] Explicit `JDFetchError` reasons: `fetch_failed`, `empty_result` (no silent fallback)
- [x] `scorer.py` — deterministic port from `scorer.go` (KeywordMatch / ExperienceFit / ImpactEvidence / ATSFormat / Readability)
- [x] `submit_keywords` MCP tool with state-error guards and graph state injection at `keywords_accept` interrupt
- [x] `extractor.py` — PDF / DOCX / TXT resume text extraction
- [x] Archived openspec changes: `2026-05-02-langgraph-pipeline-go-subprocess`, `2026-05-02-v2-noop-graph-skeleton`, `2026-05-03-host-keyword-handoff`, `2026-05-03-implement-jd-fetch-crawl4ai`

In-flight (not yet archived): `openspec/changes/pdf-output-wiring/` —
rewires the keystone `tailor → render → parse_final → score_final`
round-trip with a vendored LaTeX skeleton + tectonic. See Epic 2.

---

## Epic 1 — Installable Package + CI/CD + Release-Please ✅ COMPLETE

Makes pi-apply installable as a CLI tool (like `go-apply install`) with a `setup-mcp` command,
parity CI, and release-please for semver releases driven by conventional commits.

### 1a — CLI Entry Point

- [x] Add `typer` and `rich` to dependencies
- [x] Create `pi_apply/cli.py` with `typer.Typer()` app
  - [x] `pi-apply serve` — starts the FastMCP MCP server (replaces `uv run python main.py`)
  - [x] `pi-apply setup-mcp` — create a resusable interface
  - [x] `pi-apply setup-mcp` — implements the interface to write MCP server config to `~/.claude.json` under `mcpServers["pi-apply"]`
  - [x] `pi-apply setup-mcp` — implements the interface to write MCP server config to `~/.codex/config.toml` under `mcpServers["pi-apply"]`. use docs mcp
  - [x] `pi-apply logs` — tails `~/.local/state/pi-apply/server.log` (XDG state dir)
  - [x] `pi-apply version` — prints version from `importlib.metadata`
- [x] Add entry point to `pyproject.toml`:
  ```toml
  [project.scripts]
  pi-apply = "pi_apply.cli:app"
  ```
- [x] `setup-mcp` writes correct config shape:
  ```json
  { "mcpServers": { "pi-apply": { "command": "pi-apply", "args": ["serve"] } } }
  ```
- [x] `setup-mcp` is idempotent — does not duplicate entry if already present
- [x] Tests for `setup-mcp` idempotency and config shape

### 1b — Makefile

- [x] `Makefile` with targets mirroring go-apply:
  - [x] `make install` — `uv tool install .` (installs `pi-apply` to PATH)
  - [x] `make build` — `uv build` (wheel + sdist to `dist/`)
  - [x] `make check` — fmt + lint + type + test-unit (mirrors CI, run before pushing)
  - [x] `make test-unit` — `pytest tests/ -m "not integration"`
  - [x] `make test-integration` — `pytest tests/ -m integration`
  - [x] `make fmt` — `ruff format .`
  - [x] `make lint` — `ruff check .`
  - [x] `make type` — `pyright`
  - [x] `make clean` — `rm -rf dist/ .ruff_cache/ __pycache__/`
- [x] `make install` prints install location on success
- [x] `INSTALL_DIR` override: `make install INSTALL_DIR=~/.bin`

### 1c — GitHub Actions CI

- [x] `.github/workflows/ci.yml`
  - [x] Triggers: push to any branch, PR to `main` and `dev`
  - [x] Jobs (all must pass before merge):
    - [x] `fmt` — `ruff format --check .`
    - [x] `lint` — `ruff check .`
    - [x] `type` — `pyright`
    - [x] `test-unit` — `pytest tests/ -m "not integration" --tb=short`
    - [x] `test-integration` — `pytest tests/ -m integration --tb=short`
  - [x] Cache: `uv` cache keyed on `pyproject.toml` + `uv.lock`
  - [x] Python 3.12 pinned
- [x] `.github/workflows/release-please.yml`
  - [x] Trigger: push to `main`
  - [x] `google-github-actions/release-please-action@v4`
  - [x] Release type: `python`
  - [x] Bumps `version` in `pyproject.toml`
  - [x] Creates GitHub release with changelog from conventional commits
  - [x] On release created: build wheel + sdist, attach to release as assets
- [x] `release-please-config.json`:
  ```json
  { "release-type": "python", "packages": { ".": {} } }
  ```
- [x] `.release-please-manifest.json` initialized with `{"." : "0.1.0"}`

### 1d — Dev Tooling

- [x] Add to `[dependency-groups] dev`: `ruff`, `pyright`, `pytest-cov`, `pytest-mock`
- [x] `[tool.ruff]` in `pyproject.toml`: `line-length = 100`, `target-version = "py312"`, select `E,F,I,N,UP,B,SIM`
- [x] `[tool.pytest.ini_options]`: `testpaths = ["tests"]`, `markers = ["integration: marks tests as integration"]`
- [x] `.python-version` pinned to `3.12`

---

## Epic 2 — Holistic Tailor + Keystone Round-Trip

**Most critical next milestone.** Owns the design for nodes that are
still stubs: `tailor`, `render`, `parse_final`, `score_final`, `report`.
The architectural justification for using LangGraph at all — the
keystone `render → parse_final → score_final` round-trip — produces no
honest score delta until this epic ships.

**Design change vs. earlier draft:** T1 (skill injection) and T2 (bullet
rewrite) are collapsed into **one holistic tailor pass**. The host
reasons about the resume as a whole and submits a single structured
`TailoredResume`. There is no `submit_tailor_t1` / `submit_tailor_t2`
split — the two-pass design was inherited from go-apply's FSM and is
not needed here.

Tracked in-flight by `openspec/changes/pdf-output-wiring/`.

### 2a — `TailoredResume` schema

- [ ] `pi_apply/render/models.py` — Pydantic model whose fields match
      `CanonicalTeXBuilder.build()` keys: `name`, `location`, `email`,
      `phone`, `linkedin`, `website`, `title`, `summary`, `skills_raw`,
      `experience_raw`, `projects_raw`, `volunteer_raw`, `education_raw`
- [ ] `state.tailored: TailoredResume | None` (replaces sentinel string field)
- [ ] Validation: required-field set + bounds checks against `parsed_initial`
- [ ] Tests: schema round-trip, validation errors

### 2b — Vendored LaTeX render path

- [ ] Vendor focused subset of resume-tailor into `pi_apply/render/`:
      `escape_tex`, `strip_em_dashes`, `build_itemize`,
      `CanonicalTeXBuilder`, `compile_tex`, `resume_skeleton.tex`
- [ ] **Do NOT** vendor `resume_modifier.py` or `latex_converter.py` (different problem)
- [ ] `tectonic` documented as system dependency (README + `.env.example`)
- [ ] Fail-fast at import time if no LaTeX compiler found (mirror `bridge.py` binary-resolution pattern)
- [ ] Tests: builder fixture round-trip, compile-on-CI smoke

### 2c — Host-handoff `submit_tailor` MCP tool

- [ ] Single tool — `submit_tailor(session_id, tailored_json)` — accepts holistic edits
- [ ] Validates JSON against `TailoredResume`
- [ ] Writes `state.tailored`, resumes graph past tailor interrupt
- [ ] No internal LLM call (host-as-brain — same pattern as `submit_keywords`)
- [ ] Apply graph adds interrupt after `score_initial`, before `tailor`
- [ ] Tests: schema validation errors, state update, interrupt resume

### 2d — Keystone round-trip (makes stubs honest)

- [ ] `render` builds `.tex` via `CanonicalTeXBuilder().build(state.tailored.model_dump())`
- [ ] `render` compiles to `~/.local/share/pi-apply/applications/<session_id>.pdf` via `compile_tex`
- [ ] `parse_final` re-extracts text from the rendered PDF via `extractor.py` — no silent fallback on extraction failure
- [ ] `score_final` runs the deterministic `scorer.score()` against the re-parsed text
- [ ] `report` surfaces initial-vs-final per-dimension delta + `format_gap_chars` (round-trip text loss)
- [ ] Integration test: full run on a real JD, assert PDF non-empty, assert delta is non-zero and matches injected keywords

---

## Epic 3 — Resume Data Layer

Persistent resume store and accomplishments. Parity with go-apply's `fs` repository layer.

**Owns the `onboard` profile-graph stub** — current `profile_nodes.onboard` returns `{"intake": {"stub": "onboard"}}` and the `onboard_user` MCP tool bypasses the graph entirely. This epic backs both with real intake + persistence.

- [ ] `pi_apply/repository/` package
- [ ] `repository/resumes.py` — file-based resume store
  - [ ] `save_resume(label, content, path) -> str` — stores to `~/.local/share/pi-apply/inputs/`
  - [ ] `get_resume(label) -> str`
  - [ ] `list_resumes() -> list[str]`
  - [ ] Dispatch by file extension: PDF, DOCX, plain text
- [ ] `repository/accomplishments.py` — JSON store, `schema_version: "1"` (compat with go-apply)
  - [ ] `save_story(story: SBIStory) -> int` — returns integer story ID
  - [ ] `list_stories() -> list[SBIStory]`
  - [ ] `get_story(id: int) -> SBIStory`
- [ ] `SBIStory(BaseModel)` — `id`, `situation`, `behavior`, `impact`, `skills: list[str]`
- [ ] XDG paths: `XDG_DATA_HOME` override → `~/.local/share/pi-apply/`
- [ ] `onboard_user`, `add_resume`, `create_story` MCP tools wired to real stores
- [ ] Tests: round-trip save/load, label collision handling, schema_version field

---

## Epic 4 — Profile Compiler + requireOnboarded Guard

Assembles `CompiledProfile` from skills + tagged stories. Gates workflow tools on profile presence.

**Owns the `compile_profile` and `create_story` profile-graph stubs.**
Both currently return sentinel values, AND the matching MCP tools call
`profile_nodes.X(state)` directly (bypassing the graph). This epic
switches the profile MCP surface to **graph state injection** at the
matching interrupt — same pattern as `submit_keywords` / `submit_tailor`.

- [ ] `pi_apply/profilecompiler.py`
- [ ] `CompiledProfile(BaseModel)` — `skills`, `stories`, `compiled_at`
- [ ] `assemble(skills, remove_skills, story_ids) -> ProfileDiff`
- [ ] `ProfileDiff(BaseModel)` — `coverage_gained`, `skills_added`, `skills_removed`, `orphaned_skills`
- [ ] Persists to `~/.local/share/pi-apply/profile-compiled.json`
- [ ] `compile_profile` MCP tool calls assembler, returns diff
- [ ] `_require_onboarded()` — structured error if no compiled profile:
  - [ ] `{"error": {"code": "not_onboarded", "next_action": "onboard_user"}}`
  - [ ] Applied to: `load_jd`, `submit_keywords`, `submit_tailor_t1`, `submit_tailor_t2`, `finalize`
- [ ] Tests: assemble with adds/removes, orphan detection, missing profile error shape

---

## Epic 5 — JD Fetching (URL Support) ✅ COMPLETE

Shipped as part of Epic 0.5. Implementation chose **Crawl4AI** over the
originally-planned Playwright + httpx fallback because Crawl4AI bundles
a stealth-mode Chromium driver and content extraction in a single dep,
matching the "minimal surface area" constraint.

- [x] `pi_apply/jd_fetcher.py` — Crawl4AI-based `fetch_jd(url) -> str`
- [x] Documented env vars: `PI_APPLY_FETCH_PAGE_TIMEOUT_MS`, `PI_APPLY_FETCH_WAIT_UNTIL`, `PI_APPLY_FETCH_OUTER_TIMEOUT_S`, `PI_APPLY_FETCH_MAGIC`
- [x] Explicit `JDFetchError` reasons (`fetch_failed`, `empty_result`) — no silent fallback
- [x] `load_jd` routes: `jd_url` first, falls back to `jd_raw_text` only on URL failure
- [x] Archived openspec change: `2026-05-03-implement-jd-fetch-crawl4ai`
- [ ] _Optional polish:_ on-disk JD cache at `~/.local/share/pi-apply/jd-cache/<url-hash>.txt` (not currently implemented; only add if a real workflow demands re-runs of the same URL)

---

## ~~Epic 6 — LLM Nodes~~ REMOVED

The host (Claude) remains the brain. Nodes are mechanical processors that apply what the
host decides — keyword extraction, edit generation, and workflow decisions stay with the
host. No internal Anthropic SDK calls. This preserves the host-as-orchestrator architecture
that go-apply established and that pi-apply intentionally carries forward.

---

## Epic 6 — Scoring Config + ATS Survival Rate

Scorer is already ported (Epic 0.5). What remains is config-driven
weights and wiring the survival-rate diff — the **only** remaining
go-apply subprocess use after `pdfrender` was deemed not a CLI.

- [x] `pi_apply/scorer.py` — deterministic port (KeywordMatch / ExperienceFit / ImpactEvidence / ATSFormat / Readability)
- [ ] `ScoringWeights(BaseModel)` loaded from `~/.config/pi-apply/defaults.json` (currently hardcoded in `scorer.py`)
- [ ] `pi_apply/defaults.json` — initial weights file (ported from go-apply `config/defaults.json`)
- [ ] `get_config` / `update_config` MCP tools — read/update weights from the config file
- [ ] ATS survival rate:
  - [ ] `preview_ats_extraction` MCP tool — renders PDF via Epic 2 path, then calls `bridge.run_survival()`
  - [ ] `survival_rate` surfaced in `report` node output and `submit_tailor` response envelope
- [ ] Tests: weight loading from config, `preview_ats_extraction` with mocked subprocess

---

## Epic 7 — LangSmith Observability

Traces LangGraph graph execution — node timings, state transitions, interrupt points.

- [ ] Add `langsmith` to dependencies
- [ ] `LANGCHAIN_TRACING_V2=true`, `LANGCHAIN_API_KEY`, `LANGCHAIN_PROJECT` in `.env.example`
- [ ] LangSmith project name: `pi-apply`
- [ ] Custom trace metadata on each run: `session_id`, `tool_name`, `resume_label`
- [ ] `make trace` — convenience target that opens LangSmith project URL
- [ ] Verify: E2E run produces visible trace in LangSmith dashboard

---

## Epic 8 — Evaluation Harness (Deterministic-First)

Automated quality checks for tailoring. Runs async post-finalize, does
not block workflow.

**Reconciled with Epic 6 (LLM Nodes) REMOVED:** the host stays the
brain; pi-apply does not make internal Anthropic SDK calls. This epic
is rescoped to a **deterministic regression suite** keyed on
`scorer.score()` deltas. An optional host-driven judge extension is
sketched as a stretch goal.

- [ ] `pi_apply/evaluation/` package
- [ ] `evaluation/dataset.py` — JD/resume pair store (~30 pairs in `~/.local/share/pi-apply/evaluation/pairs.json`)
- [ ] `evaluation/runner.py` — batch runner
  - [ ] `run_evaluation(pairs) -> EvaluationReport`
  - [ ] For each pair: full apply-graph run (with a recorded host transcript replacing live host calls), assert score delta + survival-rate within tolerance
  - [ ] Results to `~/.local/share/pi-apply/evaluation/results/<timestamp>.json`
- [ ] `make evaluate` — runs full suite and prints summary
- [ ] Tests: runner with 3 fixture pairs, result schema, regression detection
- [ ] _Stretch (host-driven judge):_ `judge_tailoring` MCP tool that returns prompt + inputs; the host (Claude) returns the rationale. Not part of the core eval loop — reserved for the capstone demo.

---

## Epic 9 — Portfolio Capstone

Final polish for interview readiness.

- [ ] `README.md` — architecture diagram, install instructions, usage
  - [ ] Architecture: Claude → FastMCP → LangGraph → Go subprocess (ASCII diagram)
  - [ ] Quick-start: `make install && pi-apply setup-mcp`
  - [ ] Comparison table: go-apply hand-rolled FSM vs LangGraph StateGraph
- [ ] Blog post: _"Replacing a hand-rolled Go FSM with LangGraph: mapping MCP tool boundaries to graph interrupts"_
  - [ ] Draft in `docs/blog-draft.md`
  - [ ] Covers: `interrupt_after` pattern, `session_id = thread_id`, SqliteSaver vs custom disk FSM
- [ ] Recorded demo (Loom or similar)
  - [ ] Claude calls pi-apply tools end-to-end on a real job posting
  - [ ] LangSmith trace visible alongside
- [ ] GitHub repo public with clean commit history

---

## Dependency Order

```
Epic 0   ✅  walking skeleton
Epic 0.5 ✅  host-handoff surface (jd_fetcher, jd_data, scorer, submit_keywords)
Epic 5   ✅  JD fetching (Crawl4AI — folded into Epic 0.5 in practice)
  │
  ├── Epic 1 (installable + CI/CD)    ← unblocks clean merges
  │
  └── Epic 2 (holistic tailor + keystone round-trip)   ← most critical product work
        │     (makes tailor / render / parse_final / score_final / report honest)
        └── Epic 3 (data layer)        — backs the `onboard` stub
              └── Epic 4 (profile compiler) — backs `compile_profile` + `create_story` stubs; switches profile MCP tools to graph state injection
                    └── Epic 6 (scoring config + survival rate)
                          └── Epic 7 (LangSmith)
                                └── Epic 8 (evaluation harness — deterministic-first)
                                      └── Epic 9 (capstone)

CI/CD (Epic 1) gates all merges from Epic 2 onward.
```

**Next action:** Epic 2 (holistic tailor + keystone round-trip) — the
keystone round-trip is what justifies LangGraph in the first place, and
ships the only nodes still returning sentinel values. Epic 1 (CLI +
CI/CD) can run in parallel since it has no overlap with the graph.
