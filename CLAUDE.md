# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Northstar

**Get the user past the ATS gate so they talk to a human recruiter.**

Every scoring, tailoring, and feedback decision must serve this goal:
- Surface real keyword and format gaps — don't paper over them.
- Never fabricate experience, skills, or metrics.
- Never keyword-stuff. Honest signal only.
- A resume that passes ATS but misrepresents the candidate is a failure.

## Project Context

callback is a standalone LangGraph MCP server (stdio only). It originated as a
replacement for go-apply's Go FSM; go-apply is now deprecated — callback's own
behavior is the source of truth.
Differentiator: defensible LangGraph stateful-agent design for an AI-engineering portfolio.
Finite maintenance horizon — build only what the walking skeleton needs (see `BRIEF.md`).

State persists via LangGraph SQLite checkpointers under `~/.local/share/callback/`.

## Commands

```bash
# Install deps
uv sync

# One-time browser setup for Crawl4AI job-description fetching
uv run playwright install chromium

# Run the MCP server (stdio)
uv run python -m callback.server

# Register MCP server entries and configure tracing env vars
uv run callback setup-mcp
uv run callback config langsmith
uv run callback config status
uv run callback config env list
uv run callback config env set CALLBACK_TRACE_BACKEND langsmith
uv run callback config env unset CALLBACK_TRACE_BACKEND
uv run callback trace-check --target env
uv run callback trace-check --target codex --emit-test-trace

# All tests
uv run pytest

# Single file / single test
uv run pytest tests/test_scorer.py
uv run pytest tests/test_scorer.py::test_keyword_match -v

# Type-check
uv run pyright

# Smoke scripts (end-to-end exercises against the graphs)
uv run python scripts/smoke_apply.py
uv run python scripts/smoke_profile.py

```

## Env Vars

- `CALLBACK_APPS_DIR`: Override where application PDFs and JSON archives are written.
- `CALLBACK_FETCH_PAGE_TIMEOUT_MS`: Override Crawl4AI per-page timeout in milliseconds. Default: `30000`.
- `CALLBACK_FETCH_WAIT_UNTIL`: Override Crawl4AI wait strategy. Default: `networkidle`.
- `CALLBACK_FETCH_OUTER_TIMEOUT_S`: Override the outer fetch timeout in seconds. Default: `35`.
- `CALLBACK_FETCH_MAGIC`: Toggle Crawl4AI stealth mode. Default: `1`; set `0`, `false`, or empty string to disable.
- `CALLBACK_TRACE_BACKEND`: Optional tracing backend. Set to `langsmith` to enable LangSmith tracing.
- `LANGSMITH_TRACING`: Must be `true` when `CALLBACK_TRACE_BACKEND=langsmith`.
- `LANGSMITH_ENDPOINT`: LangSmith API endpoint. Defaults to `https://api.smith.langchain.com`.
- `LANGSMITH_API_KEY`: Required for LangSmith tracing.
- `LANGSMITH_PROJECT`: LangSmith project name. Defaults to `Callback` when tracing is enabled.

`setup-mcp` only registers the MCP server and stays noninteractive for install
scripts. Use `callback config langsmith` or `callback config env ...` to write
env vars into Claude/Codex MCP config `env` maps. Use
`callback config status` to compare Claude/Codex env maps without writing files,
then restart the MCP host after config changes.
Tracing metadata must stay safe: `session_id`, `tool_name`, `resume_label`,
`graph_name`, and `transport` only. Never include resume text, JD body text,
wiki content, API keys, or proposed edits in trace metadata.
LangSmith decorator spans may also include safe booleans/counts and state/update
key names. Use `callback trace-check` to verify import/auth/project reachability
before a demo.
MCP graph invokes suppress native LangChain/LangGraph auto-tracing because
callback pauses graphs at host handoff points; rely on sanitized `callback.*`
tool/node spans for LangSmith demos.

## Architecture

### Two graphs, one server

`server.py` (FastMCP) exposes eight tools wired to two distinct LangGraph state graphs:

| Tool             | Graph    | Behavior                                                    |
|------------------|----------|-------------------------------------------------------------|
| `load_jd`        | apply    | Runs through `jd_fetch`, then returns JD markdown plus extraction instructions. |
| `submit_keywords`| apply    | Accepts validated host-extracted JDData, runs parse/initial score, and returns score gaps plus tailor handoff guidance. |
| `submit_tailor`  | apply    | Applies host edits, renders the tailored PDF, scores final output, and returns artifact paths/report data. Optional `output_dir` redirects the final PDF into a caller directory (e.g. a sandbox). |
| `get_wiki_pages` | apply    | Returns selected profile wiki pages for host tailoring evidence. |
| `onboard_user`   | profile  | Enters the profile graph (interrupts after `onboard`).      |
| `compile_profile`| profile  | Currently calls `profile_nodes.compile_profile` directly.   |
| `create_story`   | profile  | Currently calls `profile_nodes.create_story` directly.      |
| `check_update`   | utility  | Returns current version, latest release tag, and update status. |

All tools return JSON envelopes via `_ok` / `_err`:
- Success: `{"session_id", "status": "ok", "next_action"?, "data"?, "workflow"?}`
- Error: `{"status": "error", "error": {"stage", "code", "message", "retriable"}, "session_id"?}`

### Agent MCP Playbook

When the user asks to use callback for a job, call `load_jd`, extract JDData as the host, call `submit_keywords`, follow `workflow.next_tool`, and finish with `submit_tailor`. Return `data.pdf_path`, `data.archive_path`, `data.report`, and `data.outcome` to the user. If `workflow.next_tool` is `onboard_user` or `create_story`, collect the missing profile evidence, compile the profile, then restart the job flow with `load_jd`.

If you run in a sandboxed filesystem, callback's default output (`~/.local/share/callback/applications/`) is outside your reach. Before calling `submit_tailor`, ask the user for a full output directory inside your sandbox and pass it as `output_dir`; the final PDF (`data.pdf_path`) is then written there directly.

### Apply graph (`apply_graph.py`, `apply_nodes.py`)

Linear graph with host handoff interrupts after `jd_fetch` and before `tailor`:

```
jd_fetch → keywords_accept → parse_initial → score_initial → tailor → render
        → parse_final → score_final → report → finalize → END
```

Checkpointer DB: `~/.local/share/callback/apply-sessions.db`.
State schema: `ApplyState` in `state.py` (single Pydantic model — entire graph state).
Keyword extraction is host-owned: `callback` returns the JD markdown and extraction protocol, then stores only validated JDData submitted by the host.

### Profile graph (`profile_graph.py`, `profile_nodes.py`)

Cyclic, with interrupts after `onboard`, `compile_profile`, and `create_story`:

```
check_profile ──(no profile)──▶ onboard ─▶ compile_profile ─▶ check_orphans
              └─(exists)──────────────────────────────────────▶ check_orphans
                                                                 │
                              create_story ◀─(orphans exist)─────┤
                                    └─▶ compile_profile (cycle)  │
                                                                 ▼
                                                  END (no orphans)
```

Checkpointer DB: `~/.local/share/callback/profile-sessions.db`.
State schema: `ProfileState` in `state.py`.

**Note:** `onboard_user` enters the profile graph. `compile_profile` and
`create_story` still invoke profile nodes directly (skeleton state). Preserve
the graph-state-injection intent when extending those tools.

### Scoring (`scorer.py`)

Pure deterministic Python — no I/O, no LLM calls.

| Dimension       | Max | Signal                                    |
|-----------------|-----|-------------------------------------------|
| KeywordMatch    | 55  | Required (0.7) + preferred (0.3) keywords |
| ExperienceFit   | 15  | Years met (years-only; `None` + renormalization when not evaluable) |
| ImpactEvidence  | 10  | Quantified metric bullets                 |
| ATSFormat       | 10  | Standard section headers present          |
| Readability     | 10  | Absence of filler phrases                 |

**Rubric grounding:** each dimension must proxy a real ATS gate mechanism —
recruiter keyword/boolean search (KeywordMatch), knockout filters on
years/seniority (ExperienceFit), parse failures (ATSFormat), and the recruiter
skim (ImpactEvidence, Readability). The score predicts "will a recruiter's
search find this resume and will the skim survive it" — it does not emulate any
specific ATS vendor's ranker, and must stay deterministic.

**What this score cannot see:** work-authorization and location knockouts (the
most common auto-dispositions), title match against the req, skill recency, and
degree/clearance filters. The score is a predictor of search retrievability and
skim survival, not a guarantee — do not oversell the number in report copy.

The apply graph's `render` node uses HTML + Playwright via `callback.render.html_builder`.

### Module map

| Module               | Role |
|----------------------|------|
| `server.py`          | FastMCP tool definitions; envelope helpers (`_ok`/`_err`); structured stderr JSON logging |
| `apply_graph.py`     | `build_apply_graph()` — linear apply pipeline with host handoff interrupts |
| `apply_nodes.py`     | 10 apply nodes (`jd_fetch`, `keywords_accept`, `parse_initial`, `score_initial`, `tailor`, `render`, `parse_final`, `score_final`, `report`, `finalize`) |
| `profile_graph.py`   | `build_profile_graph()` — cyclic profile graph with router edges and interrupts |
| `profile_nodes.py`   | Profile nodes (`check_profile`, `onboard`, `compile_profile`, `check_orphans`, `create_story`) |
| `state.py`           | `ApplyState`, `ProfileState` — Pydantic schemas for each graph |
| `scorer.py`          | Deterministic ATS scorer (no I/O, no LLM) |
| `extractor.py`       | Resume text extraction (PDF via pdfplumber, DOCX via python-docx, TXT) |
| `observability.py`   | Trace config port and LangSmith adapter |

## Change Discipline

- Touch only what the current task requires.
- New scoring heuristics must map to a real ATS gate mechanism (see Scoring) and stay deterministic.
- Scoring weights and thresholds live in `ScoringConfig` (`scorer.py`) — change them there; never scatter new hardcoded weights.
- All fallbacks must be explicit, logged, and approved.
- Don't add complexity beyond the walking skeleton (see `BRIEF.md`). When tempted toward pgvector / LLM-as-judge / eval harness before the graph runs end-to-end, stop.
- Active design proposals live in `openspec/changes/`. Check there before redesigning a graph.
