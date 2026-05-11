# AGENTS.md

This file provides guidance to Codex (Codex.ai/code) when working with code in this repository.

## Northstar

**Get the user past the ATS gate so they talk to a human recruiter.**

Every scoring, tailoring, and feedback decision must serve this goal:
- Surface real keyword and format gaps — don't paper over them.
- Never fabricate experience, skills, or metrics.
- Never keyword-stuff. Honest signal only.
- A resume that passes ATS but misrepresents the candidate is a failure.

## Project Context

pi-apply is a LangGraph MCP server (stdio only) that replaces the Go FSM in go-apply.
Differentiator: defensible LangGraph stateful-agent design for an AI-engineering portfolio.
Finite maintenance horizon — build only what the walking skeleton needs (see `BRIEF.md`).

State persists via LangGraph SQLite checkpointers under `~/.local/share/pi-apply/`.

## Commands

```bash
# Install deps
uv sync

# Run the MCP server (stdio). go-apply binary must be on PATH or set GO_APPLY_BIN.
GO_APPLY_BIN=/path/to/go-apply uv run python -m pi_apply.server

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

## Architecture

### Two graphs, one server

`server.py` (FastMCP) exposes four tools wired to two distinct LangGraph state graphs:

| Tool             | Graph    | Behavior                                                    |
|------------------|----------|-------------------------------------------------------------|
| `apply`          | apply    | Runs end-to-end in a single `.invoke()` — no interrupts.    |
| `onboard_user`   | profile  | Currently calls `profile_nodes.onboard` directly (skeleton).|
| `compile_profile`| profile  | Currently calls `profile_nodes.compile_profile` directly.   |
| `create_story`   | profile  | Currently calls `profile_nodes.create_story` directly.      |

All tools return JSON envelopes via `_ok` / `_err`:
- Success: `{"session_id", "status": "ok", "next_action"?, "data"?}`
- Error: `{"status": "error", "error": {"stage", "code", "message", "retriable"}, "session_id"?}`

### Apply graph (`apply_graph.py`, `apply_nodes.py`)

Linear, no interrupts, runs to completion in one `invoke()`:

```
jd_fetch → keywords_extract → parse_initial → score_initial → tailor → render
        → parse_final → score_final → report → finalize → END
```

Checkpointer DB: `~/.local/share/pi-apply/apply-sessions.db`.
State schema: `ApplyState` in `state.py` (single Pydantic model — entire graph state).

### Profile graph (`profile_graph.py`, `profile_nodes.py`)

Cyclic, with interrupts after `onboard` and `create_story`:

```
check_profile ──(no profile)──▶ onboard ─▶ compile_profile ─▶ check_orphans
              └─(exists)──────────────────────────────────────▶ check_orphans
                                                                 │
                              create_story ◀─(orphans exist)─────┤
                                    └─▶ compile_profile (cycle)  │
                                                                 ▼
                                                  END (no orphans)
```

Checkpointer DB: `~/.local/share/pi-apply/profile-sessions.db`.
State schema: `ProfileState` in `state.py`.

**Note:** The profile MCP tools currently bypass the graph and invoke nodes directly (skeleton state). Real implementation will use graph state injection to re-enter at the appropriate node — preserve this intent when extending.

### Scoring (`scorer.py`)

Pure deterministic Python — no I/O, no LLM calls. Ported from go-apply's `scorer.go`.

| Dimension       | Max | Signal                                    |
|-----------------|-----|-------------------------------------------|
| KeywordMatch    | 45  | Required (0.7) + preferred (0.3) keywords |
| ExperienceFit   | 25  | Years met + seniority match               |
| ImpactEvidence  | 10  | Quantified metric bullets                 |
| ATSFormat       | 10  | Standard section headers present          |
| Readability     | 10  | Absence of filler phrases                 |

**Why Python, not the Go binary:** go-apply has no standalone `score` CLI (only `serve`). Logic is ~250 lines of deterministic math. Python ecosystem covers PDF/DOCX/TXT extraction; go-apply only handles PDF.

### go-apply binary dependency (`bridge.py`)

`bridge.py` resolves the go-apply binary at **import time** via `_resolve_binary()`. If the binary is not on `PATH`, set `GO_APPLY_BIN=/path/to/go-apply` before importing. In tests, `conftest.py` re-imports the module against a fake binary after resolution tests evict it from `sys.modules` — preserve this fixture when adding bridge tests.

go-apply is used for PDF rendering only. `run_pdfrender` exists in `bridge.py`; the apply graph's `render` node currently uses `fpdf2` directly.

### Module map

| Module               | Role |
|----------------------|------|
| `server.py`          | FastMCP tool definitions; envelope helpers (`_ok`/`_err`); structured stderr JSON logging |
| `apply_graph.py`     | `build_apply_graph()` — linear, no-interrupt apply pipeline |
| `apply_nodes.py`     | 10 apply nodes (`jd_fetch`, `keywords_extract`, `parse_initial`, `score_initial`, `tailor`, `render`, `parse_final`, `score_final`, `report`, `finalize`) |
| `profile_graph.py`   | `build_profile_graph()` — cyclic profile graph with router edges and interrupts |
| `profile_nodes.py`   | Profile nodes (`check_profile`, `onboard`, `compile_profile`, `check_orphans`, `create_story`) |
| `state.py`           | `ApplyState`, `ProfileState` — Pydantic schemas for each graph |
| `scorer.py`          | Deterministic ATS scorer (no I/O, no LLM) |
| `extractor.py`       | Resume text extraction (PDF via pdfplumber, DOCX via python-docx, TXT) |
| `bridge.py`          | go-apply subprocess wrapper; resolves binary at import time |

## Change Discipline

- Touch only what the current task requires.
- Don't add scoring heuristics not present in go-apply unless explicitly requested.
- Scoring weights live in config — don't hardcode them.
- All fallbacks must be explicit, logged, and approved.
- Don't add complexity beyond the walking skeleton (see `BRIEF.md`). When tempted toward pgvector / LLM-as-judge / eval harness before the graph runs end-to-end, stop.
- Active design proposals live in `openspec/changes/`. Check there before redesigning a graph.
