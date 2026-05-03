# pi-apply — Epics & Vertical Slices

Vertical slices ordered by dependency. Each epic delivers a working, testable increment.
Conventional commits required throughout (`feat:`, `fix:`, `chore:`) — release-please reads them.

---

## Epic 0 — Walking Skeleton ✅ COMPLETE

Foundation POC. LangGraph state graph running end-to-end with Go subprocess bridge and PDF output.

- [x] `uv init`, deps: `langgraph`, `langchain-core`, `pydantic`, `fastmcp`, `fpdf2`
- [x] Package structure: `pi_apply/{__init__, state, graph, bridge, nodes, server}.py`
- [x] `.env.example` documenting `GO_APPLY_BIN`, `LOG_LEVEL`, `PI_APPLY_TEST_STUB`
- [x] `pyrightconfig.json` for `.venv` type resolution
- [x] `ApplyState(BaseModel)` — typed state with 14 fields covering full pipeline
- [x] `bridge.py` — Go subprocess bridge; fail-fast binary resolution at import time
  - [x] `run_pdfrender(args) -> bytes`
  - [x] `run_survival(args) -> str`
  - [x] `EnvironmentError` on missing binary (no silent degradation)
- [x] `nodes.py` — 5 skeleton node functions with structured JSON logging
  - [x] `load_jd` — copies `jd_raw_text` → `jd_text`
  - [x] `score` — counts keyword matches against resume content
  - [x] `tailor_t1` — appends `[T1 edits: ...]` block (skeleton only)
  - [x] `tailor_t2` — appends `[T2 edits: ...]` block (skeleton only)
  - [x] `finalize` — writes JSON record + PDF to `~/.local/share/pi-apply/applications/`
- [x] `graph.py` — `StateGraph` compiled with `interrupt_after` + `SqliteSaver`
  - [x] `session_id = thread_id` mapping (no lookup table)
  - [x] `SqliteSaver` at `~/.local/share/pi-apply/sessions.db`
  - [x] `check_same_thread=False` for FastMCP threading
- [x] `server.py` — FastMCP with 12 tools and consistent JSON envelope
  - [x] `{"session_id", "status", "next_action", "data", "error"}` envelope
  - [x] `next_action` values map directly to next MCP tool name
  - [x] Structured logging (ISO 8601 UTC timestamp + level) on every call
- [x] PDF output via `fpdf2` in `finalize` node (go-apply pdfrender is not a CLI subprocess)
- [x] MCP registered in `~/.claude.json`
- [x] `/apply` slash command at `.claude/commands/apply.md`
- [x] 47 tests — all passing
  - [x] `test_state.py` (11) — field validation, optional/required
  - [x] `test_bridge.py` (8) — binary resolution, `importlib.reload` pattern
  - [x] `test_nodes.py` (12) — deltas, error logging, `_NotSerializable` ERROR path
  - [x] `test_graph.py` (2) — checkpoint round-trip, full pipeline end-to-end
  - [x] `test_server.py` (14) — 12 tool registration, routing, ordering enforcement
- [x] E2E validated: PlayStation SWE II Data Platform JD — 14/14 skeleton score, 7/14 honest coverage

---

## Epic 1 — Installable Package + CI/CD + Release-Please

Makes pi-apply installable as a CLI tool (like `go-apply install`) with a `setup-mcp` command,
parity CI, and release-please for semver releases driven by conventional commits.

### 1a — CLI Entry Point

- [ ] Add `typer` and `rich` to dependencies
- [ ] Create `pi_apply/cli.py` with `typer.Typer()` app
  - [ ] `pi-apply serve` — starts the FastMCP MCP server (replaces `uv run python main.py`)
  - [ ] `pi-apply setup-mcp` — writes MCP server config to `~/.claude.json` under `mcpServers["pi-apply"]`
  - [ ] `pi-apply logs` — tails `~/.local/state/pi-apply/server.log` (XDG state dir)
  - [ ] `pi-apply version` — prints version from `importlib.metadata`
- [ ] Add entry point to `pyproject.toml`:
  ```toml
  [project.scripts]
  pi-apply = "pi_apply.cli:app"
  ```
- [ ] `setup-mcp` writes correct config shape:
  ```json
  { "mcpServers": { "pi-apply": { "command": "pi-apply", "args": ["serve"] } } }
  ```
- [ ] `setup-mcp` is idempotent — does not duplicate entry if already present
- [ ] Tests for `setup-mcp` idempotency and config shape

### 1b — Makefile

- [ ] `Makefile` with targets mirroring go-apply:
  - [ ] `make install` — `uv tool install .` (installs `pi-apply` to PATH)
  - [ ] `make build` — `uv build` (wheel + sdist to `dist/`)
  - [ ] `make check` — fmt + lint + type + test-unit (mirrors CI, run before pushing)
  - [ ] `make test-unit` — `pytest tests/ -m "not integration"`
  - [ ] `make test-integration` — `pytest tests/ -m integration`
  - [ ] `make fmt` — `ruff format .`
  - [ ] `make lint` — `ruff check .`
  - [ ] `make type` — `pyright`
  - [ ] `make clean` — `rm -rf dist/ .ruff_cache/ __pycache__/`
- [ ] `make install` prints install location on success
- [ ] `INSTALL_DIR` override: `make install INSTALL_DIR=~/.bin`

### 1c — GitHub Actions CI

- [ ] `.github/workflows/ci.yml`
  - [ ] Triggers: push to any branch, PR to `main` and `dev`
  - [ ] Jobs (all must pass before merge):
    - [ ] `fmt` — `ruff format --check .`
    - [ ] `lint` — `ruff check .`
    - [ ] `type` — `pyright`
    - [ ] `test-unit` — `pytest tests/ -m "not integration" --tb=short`
    - [ ] `test-integration` — `pytest tests/ -m integration --tb=short`
  - [ ] Cache: `uv` cache keyed on `pyproject.toml` + `uv.lock`
  - [ ] Python 3.12 pinned
- [ ] `.github/workflows/release-please.yml`
  - [ ] Trigger: push to `main`
  - [ ] `google-github-actions/release-please-action@v4`
  - [ ] Release type: `python`
  - [ ] Bumps `version` in `pyproject.toml`
  - [ ] Creates GitHub release with changelog from conventional commits
  - [ ] On release created: build wheel + sdist, attach to release as assets
- [ ] `release-please-config.json`:
  ```json
  { "release-type": "python", "packages": { ".": {} } }
  ```
- [ ] `.release-please-manifest.json` initialized with `{"." : "0.1.0"}`

### 1d — Dev Tooling

- [ ] Add to `[dependency-groups] dev`: `ruff`, `pyright`, `pytest-cov`, `pytest-mock`
- [ ] `[tool.ruff]` in `pyproject.toml`: `line-length = 100`, `target-version = "py312"`, select `E,F,I,N,UP,B,SIM`
- [ ] `[tool.pytest.ini_options]`: `testpaths = ["tests"]`, `markers = ["integration: marks tests as integration"]`
- [ ] `.python-version` pinned to `3.12`

---

## Epic 2 — Real T1/T2 Edit Application

**Most critical next milestone.** Tailoring currently appends raw JSON patches.
This epic makes T1 inject keywords into the skills section and T2 rewrite experience bullets.

### 2a — Resume Section Parser

- [ ] `pi_apply/resume.py` — section parser for plain-text resumes
- [ ] `parse_sections(text: str) -> ResumeDoc`
  - [ ] Identifies skills section by heading heuristics ("Skills", "Technical Skills", etc.)
  - [ ] Identifies experience section and individual job blocks
  - [ ] Identifies experience bullets within each job block
- [ ] `ResumeDoc(BaseModel)`:
  - [ ] `skills: dict[str, list[str]]` — category → skills list
  - [ ] `jobs: list[JobBlock]` — each with `title`, `company`, `bullets: list[str]`
  - [ ] `raw: str` — original text preserved
- [ ] `render_text(doc: ResumeDoc) -> str` — serializes back to plain text
- [ ] Round-trip invariant: `render_text(parse_sections(text))` ≈ `text` (whitespace-normalized)
- [ ] Tests: 5+ resume fixtures covering formatting variations

### 2b — Edit Schema

- [ ] `pi_apply/edits.py`
- [ ] `SkillInjection(BaseModel)` — `category: str`, `skills: list[str]`
- [ ] `BulletRewrite(BaseModel)` — `job_index: int`, `bullet_index: int`, `rewritten: str`
- [ ] `T1Edits(BaseModel)` — `injections: list[SkillInjection]`
- [ ] `T2Edits(BaseModel)` — `rewrites: list[BulletRewrite]`
- [ ] Validation: `job_index` and `bullet_index` within bounds of parsed resume
- [ ] Tests for out-of-bounds validation

### 2c — Real T1 Node

- [ ] `tailor_t1` applies `T1Edits` from `state.edits_t1`
- [ ] Parses resume, injects skills into correct category (creates category if missing)
- [ ] Deduplication: does not inject skill already present
- [ ] `state.tailored_t1` = rendered plain text of modified resume
- [ ] Tests: injection into existing category, new category, dedup

### 2d — Real T2 Node

- [ ] `tailor_t2` applies `T2Edits` from `state.edits_t2`
- [ ] Applies bullet rewrites by index against parsed `tailored_t1`
- [ ] Preserves unmentioned bullets unchanged
- [ ] `state.tailored_t2` = fully tailored plain-text resume
- [ ] Tests: single rewrite, multiple rewrites, out-of-bounds handling

### 2e — Clean PDF Output

- [ ] `finalize` renders `state.tailored_t2` (not skeleton append output)
- [ ] PDF uses proper section formatting (bold headings, consistent spacing)
- [ ] Integration test: full run, assert PDF content contains injected keywords

---

## Epic 3 — Resume Data Layer

Persistent resume store and accomplishments. Parity with go-apply's `fs` repository layer.

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

## Epic 5 — JD Fetching (URL Support)

`load_jd` currently only handles `jd_raw_text`. This epic wires Playwright + httpx fallback.

- [ ] Add `playwright` and `httpx` to dependencies
- [ ] `pi_apply/fetcher.py`
  - [ ] `fetch_jd(url: str) -> str` — returns extracted text
  - [ ] Playwright primary: headless Chromium, `page.inner_text("body")`
  - [ ] httpx + BeautifulSoup fallback for non-JS pages
  - [ ] `FetchError(url, reason)` on failure — no silent fallback
  - [ ] Caches result to `~/.local/share/pi-apply/jd-cache/<url-hash>.txt`
- [ ] `load_jd` routes: `jd_url` present → `fetch_jd()`, else `jd_raw_text` direct
- [ ] Tests: httpx path with mock response, cache hit/miss, `FetchError` propagation
- [ ] Integration test: real URL fetch (marked `@pytest.mark.integration`)

---

## ~~Epic 6 — LLM Nodes~~ REMOVED

The host (Claude) remains the brain. Nodes are mechanical processors that apply what the
host decides — keyword extraction, edit generation, and workflow decisions stay with the
host. No internal Anthropic SDK calls. This preserves the host-as-orchestrator architecture
that go-apply established and that pi-apply intentionally carries forward.

---

## Epic 6 — Scoring + ATS Survival Rate

Ports deterministic scorer from Go. Wires the survival diff pipeline.

- [ ] `pi_apply/scorer.py`
  - [ ] `score(resume_text, keywords, weights) -> ScoreResult`
  - [ ] `ScoreResult(BaseModel)` — `score: float`, `matched`, `missing`, `survival_rate: float | None`
  - [ ] `ScoringWeights(BaseModel)` — loaded from `~/.config/pi-apply/defaults.json`
- [ ] `pi_apply/defaults.json` — initial weights (ported from go-apply `config/defaults.json`)
- [ ] `submit_keywords` calls scorer after state update
- [ ] ATS survival rate:
  - [ ] `preview_ats_extraction` renders PDF then calls `bridge.run_survival()`
  - [ ] `survival_rate` surfaced in `submit_keywords` response envelope
- [ ] Tests: scorer unit tests, weight loading from config

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

## Epic 8 — Evaluation Harness + LLM-as-Judge

Automated quality checks for tailoring. Runs async post-finalize, does not block workflow.

- [ ] `pi_apply/evaluation/` package
- [ ] `evaluation/dataset.py` — JD/resume pair store (30+ pairs in `~/.local/share/pi-apply/evaluation/pairs.json`)
- [ ] `evaluation/judge.py` — LLM-as-judge for tailoring quality
  - [ ] `judge_tailoring(original, tailored, keywords) -> JudgeResult`
  - [ ] `JudgeResult(BaseModel)` — `score: float`, `rationale: str`, `keyword_coverage: float`
  - [ ] Scoring criteria: keyword density + readability + honesty (no invented skills)
- [ ] `evaluation/runner.py` — batch runner
  - [ ] `run_evaluation(pairs) -> EvaluationReport`
  - [ ] Results to `~/.local/share/pi-apply/evaluation/results/<timestamp>.json`
- [ ] Post-finalize: `finalize` node enqueues async judge call (non-blocking)
- [ ] `make evaluate` — runs full suite and prints summary
- [ ] Tests: judge mock, runner with 3 pairs, result schema

---

## Epic 9 — Portfolio Capstone

Final polish for interview readiness.

- [ ] `README.md` — architecture diagram, install instructions, usage
  - [ ] Architecture: Claude → FastMCP → LangGraph → Go subprocess (ASCII diagram)
  - [ ] Quick-start: `make install && pi-apply setup-mcp`
  - [ ] Comparison table: go-apply hand-rolled FSM vs LangGraph StateGraph
- [ ] Blog post: *"Replacing a hand-rolled Go FSM with LangGraph: mapping MCP tool boundaries to graph interrupts"*
  - [ ] Draft in `docs/blog-draft.md`
  - [ ] Covers: `interrupt_after` pattern, `session_id = thread_id`, SqliteSaver vs custom disk FSM
- [ ] Recorded demo (Loom or similar)
  - [ ] Claude calls pi-apply tools end-to-end on a real job posting
  - [ ] LangSmith trace visible alongside
- [ ] GitHub repo public with clean commit history

---

## Dependency Order

```
Epic 0 ✅
  └── Epic 1 (installable + CI/CD)       ← next — unblocks clean merges
        ├── Epic 2 (real T1/T2)           ← most critical product work
        │     └── Epic 3 (data layer)
        │           └── Epic 4 (profile compiler)
        │                 └── Epic 5 (JD fetching)
        │                       └── Epic 6 (scoring + survival)
        │                             └── Epic 7 (LangSmith)
        │                                   └── Epic 8 (evaluation harness)
        │                                         └── Epic 9 (capstone)
        └── CI/CD gates all merges from Epic 2 onward
```

**Next action:** Epic 1a — CLI entry point (`pi-apply serve` + `pi-apply setup-mcp`).
