# AGENTS.md

This file provides guidance to Codex when working in this repository.

## Northstar

**Get the user past the ATS gate so they talk to a human recruiter.**

Every scoring, tailoring, and feedback decision must serve this goal:
- Surface real keyword and format gaps - don't paper over them.
- Never fabricate experience, skills, or metrics.
- Never keyword-stuff. Honest signal only.
- A resume that passes ATS but misrepresents the candidate is a failure.

## Project Context

callback is a standalone LangGraph MCP server (stdio only). It originated as a replacement for go-apply's Go FSM; go-apply is now deprecated and is not a parity target — callback's own behavior is the source of truth.
Differentiator: defensible LangGraph stateful-agent design for an AI-engineering portfolio.
Finite maintenance horizon - build only what the walking skeleton needs.
`BRIEF.md` is the project charter/history; this file is the active working guide.

State persists via LangGraph SQLite checkpointers under `~/.local/share/callback/`.
Logs default to `~/.local/state/callback/server.log`.

## Commands

```bash
# Install deps
uv sync

# Install Playwright Chromium for Crawl4AI URL fetching
callback install-browsers

# Run the MCP server (stdio)
uv run python -m callback.server

# Or run the packaged CLI
uv run callback serve

# Register the MCP server with Claude and Codex
uv run callback setup-mcp

# Configure LangSmith tracing env vars in Claude/Codex MCP configs
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

## Environment

- `GO_APPLY_BIN`: Legacy; read only by `bridge.py`, which is wired into nothing at runtime.
- `LOG_LEVEL`: Server log level.
- `CALLBACK_LOG_PATH`: Override the server log file path.
- `CALLBACK_APPS_DIR`: Override where application PDFs and JSON archives are written.
- `CALLBACK_FETCH_PAGE_TIMEOUT_MS`: Crawl4AI per-page timeout in milliseconds.
- `CALLBACK_FETCH_WAIT_UNTIL`: Crawl4AI wait strategy.
- `CALLBACK_FETCH_OUTER_TIMEOUT_S`: Outer fetch timeout in seconds.
- `CALLBACK_FETCH_MAGIC`: Enable or disable Crawl4AI stealth mode.
- `CALLBACK_TRACE_BACKEND`: Optional tracing backend. Set to `langsmith` to enable the LangSmith adapter.
- `LANGSMITH_TRACING`: Must be `true` when `CALLBACK_TRACE_BACKEND=langsmith`.
- `LANGSMITH_ENDPOINT`: LangSmith API endpoint. Defaults to `https://api.smith.langchain.com`.
- `LANGSMITH_API_KEY`: Required for LangSmith tracing.
- `LANGSMITH_PROJECT`: LangSmith project name. Defaults to `Callback` when tracing is enabled.
- `XDG_DATA_HOME`: Overrides resume, wiki, and profile data roots.

`callback setup-mcp` is noninteractive and only registers the MCP server entry.
Use `callback config langsmith` or `callback config env ...` to write env vars
into Claude/Codex MCP config `env` maps. Use `callback config status` to compare
Claude/Codex env maps without writing files. Restart the MCP host after config
changes. Tracing is opt-in; trace metadata must stay safe and compact:
`session_id`, `tool_name`, `resume_label`, `graph_name`, and `transport` only.
Do not include resume text, JD body text, wiki page content, API keys, or edits
in trace metadata.
LangSmith decorator spans may additionally include safe booleans/counts and
state/update key names, but never raw values or file paths. Use
`callback trace-check` to verify import/auth/project reachability before a demo.
MCP graph invokes suppress native LangChain/LangGraph auto-tracing because
callback pauses graphs at host handoff points; rely on sanitized `callback.*`
tool/node spans for LangSmith demos.

## Architecture

### Architecture pattern

Use a workflow-first ports-and-adapters shape around LangGraph. This is not an
MVC or MVVM app; those patterns fit UI applications. For callback, think:

```text
MCP adapter / controller
        |
LangGraph workflow
        |
Workflow nodes / use cases
        |
Domain services
        |
Infrastructure adapters
```

Layer rules:
- `server.py` is the MCP adapter: tool definitions, envelope shaping, session handoff, and host-facing workflow guidance.
- `apply_graph.py` and `profile_graph.py` own graph wiring, routing, checkpointers, and interrupt boundaries.
- `apply_nodes.py` and `profile_nodes.py` own workflow step handlers. Keep them focused on graph state transitions and use existing services/adapters for specialized work.
- Domain services stay deterministic and easy to test: `scorer.py`, `section_map.py`, `jd_data.py`, and `profilecompiler.py`.
- Infrastructure adapters own I/O boundaries: `jd_fetcher.py`, `extractor.py`, `render/`, `wiki.py`, `repository/`, `bridge.py`, and `version_check.py`.
- Observability adapters live behind `observability.py`; graph code may ask for trace config, but workflow nodes should not know vendor details.

The key boundary: the host owns LLM reasoning and judgment. callback owns state,
validation, deterministic scoring, rendering, archival, and explicit workflow
handoff metadata.

### Two graphs, one server

`server.py` (FastMCP) exposes eight tools wired to two distinct LangGraph state graphs:

| Tool | Graph | Behavior |
|---|---|---|
| `load_jd` | apply | Loads JD markdown, resolves a resume label, and returns host extraction instructions. |
| `submit_keywords` | apply | Accepts host-extracted JDData, runs parse/initial score, and returns score gaps plus tailor handoff guidance. |
| `submit_tailor` | apply | Applies host edits, resumes the graph, and finalizes the PDF/report artifacts. |
| `get_wiki_pages` | apply | Reads wiki pages for the active resume label. |
| `onboard_user` | profile | Starts profile intake and registers the resume plus optional source files. |
| `compile_profile` | profile | Recompiles the profile from stored stories and host tags. |
| `create_story` | profile | Persists a behavioral story for a skill. |
| `check_update` | utility | Returns current version, latest release tag, and update status. |

All tools return JSON envelopes via `_ok` / `_err`:
- Success: `{"session_id", "status": "ok", "next_action"?, "data"?, "workflow"?}`
- Error: `{"status": "error", "error": {"stage", "code", "message", "retriable"}, "session_id"?}`

### Agent MCP Playbook

When the user asks to use callback for a job, the host should follow the workflow metadata:

1. Call `load_jd` with `jd_url` or `jd_raw_text`.
2. Extract compact JDData from `data.jd_text` using `data.extraction_protocol`.
3. Call `submit_keywords` with the same `session_id` and the compact `jd_json` string.
4. If `workflow.next_tool` is `get_wiki_pages`, use `data.wiki_index` to fetch relevant evidence pages, then call `submit_tailor`.
5. If `workflow.next_tool` is `submit_tailor`, create honest edits from `data.sections`, `data.score_gap`, wiki evidence, and `data.tailor_instructions`.
6. If `workflow.next_tool` is `onboard_user` or `create_story`, collect the missing profile evidence, compile the profile, then restart the job flow with `load_jd`.
7. After `submit_tailor`, return `data.pdf_path`, `data.archive_path`, `data.report`, and `data.outcome` to the user.

The host owns keyword extraction and tailoring judgment. callback owns state, validation, rendering, scoring, and archival.

### Apply graph (`apply_graph.py`, `apply_nodes.py`)

Linear graph with host handoff interrupts after `jd_fetch` and `keywords_accept`:

```text
jd_fetch -> keywords_accept -> parse_initial -> score_initial -> tailor -> render
        -> parse_final -> score_final -> report -> finalize -> END
```

`submit_tailor` resumes at `tailor`.

Checkpointer DB: `~/.local/share/callback/apply-sessions.db`.
State schema: `ApplyState` in `state.py` (single Pydantic model - entire graph state).
Keyword extraction is host-owned: `load_jd` returns the JD markdown and extraction protocol, then `submit_keywords` stores only validated JDData submitted by the host.

### Profile graph (`profile_graph.py`, `profile_nodes.py`)

Cyclic, with interrupts after `onboard`, `compile_profile`, and `create_story`:

```text
check_profile -> onboard -> compile_profile -> check_orphans
      |            ^             |
      |            |             v
      +---------- check_orphans <- create_story
```

Checkpointer DB: `~/.local/share/callback/profile-sessions.db`.
State schema: `ProfileState` in `state.py`.

Current profile MCP behavior:
- `onboard_user` enters the profile graph.
- `compile_profile` and `create_story` still call node functions directly.
- Preserve the graph-state-injection intent when extending these tools.

### JD Fetching (`jd_fetcher.py`)

URL fetching uses Crawl4AI. The fetch surface is controlled by:
- `CALLBACK_FETCH_PAGE_TIMEOUT_MS`
- `CALLBACK_FETCH_WAIT_UNTIL`
- `CALLBACK_FETCH_OUTER_TIMEOUT_S`
- `CALLBACK_FETCH_MAGIC`

Do not add a silent fallback path if URL fetch fails.

### Scoring (`scorer.py`)

Pure deterministic Python - no I/O, no LLM calls.

| Dimension | Max | Signal |
|---|---|---|
| KeywordMatch | 45 | Required (0.7) + preferred (0.3) keywords |
| ExperienceFit | 25 | Years met + seniority match |
| ImpactEvidence | 10 | Quantified metric bullets |
| ATSFormat | 10 | Standard section headers present |
| Readability | 10 | Absence of filler phrases |

### Rendering and bridge (`render/`, `bridge.py`)

PDF rendering uses HTML + Playwright in `callback/render/html_builder.py`.
go-apply is deprecated and its binary is wired into nothing at runtime — `bridge.py` is a dead legacy adapter kept only for its tests, not a design reference.
It resolves the binary at import time; tests point it at a fake binary (see `tests/conftest.py`).

### Module map

| Module | Role |
|---|---|
| `server.py` | FastMCP tool definitions, envelope helpers, structured JSON logging |
| `apply_graph.py` | `build_apply_graph()` - linear apply pipeline with host handoff interrupts |
| `apply_nodes.py` | Apply nodes (`jd_fetch`, `keywords_accept`, `parse_initial`, `score_initial`, `tailor`, `render`, `parse_final`, `score_final`, `report`, `finalize`) |
| `profile_graph.py` | `build_profile_graph()` - cyclic profile graph with router edges and interrupts |
| `profile_nodes.py` | Profile nodes (`check_profile`, `onboard`, `compile_profile`, `check_orphans`, `create_story`) |
| `state.py` | `ApplyState`, `ProfileState`, and related profile data models |
| `scorer.py` | Deterministic ATS scorer |
| `jd_data.py` | JD JSON schema, extraction protocol, and validators |
| `jd_fetcher.py` | Crawl4AI job-description fetcher |
| `extractor.py` | Resume text extraction (PDF, DOCX, TXT, Markdown/plain text) |
| `section_map.py` | Resume section editing helpers |
| `wiki.py` | Wiki storage for resume-linked behavioral stories |
| `repository/` | Resume and accomplishments persistence helpers |
| `profilecompiler.py` | Compiles skills and stories into a profile summary |
| `render/` | HTML + Playwright resume rendering |
| `bridge.py` | dead legacy go-apply adapter (kept for tests only) |
| `cli.py` | `callback` CLI entry point |
| `observability.py` | Trace config port and LangSmith adapter |
| `version_check.py` | Current-vs-latest release comparison |

## Change Discipline

- Touch only what the current task requires.
- New scoring heuristics must map to a real ATS gate mechanism and stay deterministic — go-apply parity is no longer a constraint.
- Scoring weights live in config - don't hardcode them.
- All fallbacks must be explicit, logged, and approved.
- Don't add complexity beyond the walking skeleton. When tempted toward pgvector, LLM-as-judge, provider clients, RAG, or an eval harness, stop unless there is an explicit OpenSpec proposal for it.
- Do not move keyword extraction, evidence selection, or resume-tailoring judgment into callback server-side LLM calls unless explicitly requested through a proposal.
- Do not organize new work as MVC/MVVM. Use the workflow-first ports-and-adapters pattern above.
- Active design proposals live in `openspec/changes/`. Check there before redesigning a graph.
