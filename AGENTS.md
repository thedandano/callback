# AGENTS.md

This file provides guidance to Codex when working in this repository.

## Northstar

**Get the user past the ATS gate so they talk to a human recruiter.**

Every scoring, tailoring, and feedback decision must serve this goal:
- Surface real keyword and format gaps - don't paper over them.
- Never fabricate experience, skills, or metrics.
- Never keyword-stuff. Honest signal only.
- A resume that passes ATS but misrepresents the candidate is a failure.

## Constitution

Non-negotiable principles. These do not change without an explicit design proposal.

1. **Scoring is pure and deterministic.** The scorer (`scorer.py`) performs literal keyword
   matching only — no synonyms, no semantic expansion, no abbreviation unfolding, no LLM
   calls. The score measures what the resume literally contains: a conservative,
   defensible lower bound, not an estimate of what a human reader would infer.
2. **Scoring measures; tailoring acts.** The scorer's job is to determine the score and
   report gaps. How to close those gaps — which edits raise the score — belongs entirely
   to the tailoring side (host judgment at graph interrupts). The scorer must never
   silently cover a gap the tailoring loop should see and act on.

## Code Review Rules

The goal of a review here is full coverage, not a highlight reel. We would
rather read ten real findings than have the two most obvious ones posted and
the rest dropped. Read every changed file and every hunk before writing
anything, and keep going after the first findings.

For each change, read enough of the surrounding code to judge it in context:
the callers of any function whose behavior or signature changed, the tests
that cover it, and any code that relies on the old behavior. Many of the bugs
we care about are not visible in the diff alone.

What to look for, in priority order:

1. Correctness: code that does not do what it claims. Wrong conditions,
   off-by-one errors, unhandled null or empty cases, incorrect async or
   concurrency handling, wrong types or units, errors swallowed or handled
   incorrectly, edge cases that crash or return wrong results.
2. Bad logic: code that runs but whose reasoning is flawed. Unreachable or
   redundant branches, conditions that are always true or false, state that
   can become inconsistent, an approach that cannot work for inputs the code
   is clearly meant to handle.
3. Regressions: existing behavior this change breaks. Changed defaults,
   removed or renamed things that are still used elsewhere, altered return
   shapes, changed ordering or timing, tests deleted or weakened to make the
   change pass.
4. Security: injection, missing authentication or authorization checks,
   secrets in code or logs, unsafe deserialization, path traversal, unvalidated
   input reaching a sensitive operation, overly broad permissions.
5. Bad practices that will cause real problems: duplicated logic that will
   drift, new behavior with no test coverage, dead code, misleading names,
   functions doing several unrelated things, resource leaks, hardcoded values
   that should be configuration.

Severity: treat everything in categories 1 to 4 as P1 at minimum, and P0 if
it could cause data loss, a security breach, or an outage. Treat category 5
as P1 when it affects maintainability or testability of the changed code.
Pure style preferences that a formatter or linter would catch are not worth
a comment.

For each finding, give the file and line, what is wrong, a concrete scenario
where it fails (the input or state, and the wrong result), and a suggested
fix. If you are unsure whether something is a bug, say so and post it
anyway with what you would need to check; an uncertain finding is more
useful to us than a missing one.

## Project Context

callback is a standalone LangGraph MCP server (stdio only). It originated as a replacement for go-apply's Go FSM; go-apply is now deprecated — callback's own behavior is the source of truth.
Differentiator: defensible LangGraph stateful-agent design for an AI-engineering portfolio.
Finite maintenance horizon - build only what the walking skeleton needs.
`BRIEF.md` is the project charter/history; this file is the active working guide.

Session state persists via LangGraph SQLite checkpointers in the per-user temp folder.
Logs default to `~/.local/state/callback/server.log`.

### Cross-harness plugin packaging

- Keep one shared plugin body at the repository root: `skills/` contains the
  host-neutral workflows, `.mcp.json` serves Claude, Codex, and generic MCP
  clients, and root `plugin.json` plus `mcp.json` serves Hermes and other Agent
  Plugins v1 hosts.
- Keep host-specific manifests as thin adapters. Do not copy or fork skills per
  harness, and do not add a native Hermes wrapper while the portable package
  covers the requirement.
- Add future harnesses by reusing the shared skills and server, with only the
  smallest discovery or launch adapter that the host requires.

## Commands

```bash
# Install deps
uv sync

# Install Playwright Chromium for URL fetching and PDF rendering
callback install-browsers

# Run the MCP server (stdio)
uv run python -m callback.server

# Or run the packaged CLI
uv run callback serve

# Configure LangSmith tracing env vars in callback's own settings file (~/.config/callback/env.json)
uv run callback config langsmith
uv run callback config status
uv run callback config env list
uv run callback config env set CALLBACK_TRACE_BACKEND langsmith
uv run callback config env unset CALLBACK_TRACE_BACKEND
uv run callback trace-check
uv run callback trace-check --emit-test-trace

# One-time import of old run archives, the record CSV, and the old contact ledger (safe to re-run)
uv run callback ledger import --archives <folder> --csv <record.csv> --contacts-db <old.sqlite3>

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

# Evals (E3 runs in CI; E1/E2 need a host model and are marked `local`)
uv run pytest -m "not local" evals/                    # E3 + check unit tests (CI)
uv run python scripts/run_evals.py                     # E1 + E2 against `claude -p`, writes host outputs
uv run python scripts/run_evals.py --host codex --model gpt-5.6-terra --eval tailor
uv run python scripts/run_evals.py --host hermes        # saved/default model
uv run python scripts/run_evals.py --host ollama --model MODEL_NAME --port 11434
uv run python scripts/run_evals.py --host llamacpp --model MODEL_ALIAS --port 8080
uv run python scripts/run_evals.py --checks-only       # re-check saved outputs, no model call, no LangSmith upload
uv run pytest -m local evals/                          # E1 + E2 checks over the saved host outputs
# baseline 2026-09-07, claude default model: E1 2/6 (PASS cedar/reddit), E2 1/8 (see INTENT §M6)
```

## Environment

- `LOG_LEVEL`: Server log level.
- `CALLBACK_LOG_PATH`: Override the server log file path.
- `CALLBACK_APPS_DIR`: Override the root where application PDFs are written; each run gets `<root>/<YYYY-MM-DD>/<company-role-slug>/`. It moves only the PDFs, not the other data roots or the ledger. `submit_tailor`'s `output_dir` argument overrides it per call.
- `CALLBACK_FETCH_PAGE_TIMEOUT_MS`: Override the Playwright page-load timeout in milliseconds. Default: `30000`.
- `CALLBACK_FETCH_OUTER_TIMEOUT_S`: Override the outer fetch timeout in seconds. Default: `35`.
- `CALLBACK_TRACE_BACKEND`: Optional tracing backend. Set to `langsmith` to enable the LangSmith adapter.
- `LANGSMITH_TRACING`: Must be `true` when `CALLBACK_TRACE_BACKEND=langsmith`.
- `LANGSMITH_ENDPOINT`: LangSmith API endpoint. Defaults to `https://api.smith.langchain.com`.
- `LANGSMITH_API_KEY`: Required for LangSmith tracing; also gates eval experiment recording. The runner logs a WARNING and skips recording when unset.
- `LANGSMITH_PROJECT`: LangSmith project name. Defaults to `Callback` when tracing is enabled.
- `XDG_DATA_HOME`: Moves the whole data root (resumes, wiki, compiled profile, ledger, default PDF folder) from `~/.local/share/callback` to `$XDG_DATA_HOME/callback`.
- `XDG_STATE_HOME`: Moves the state root (server log) from `~/.local/state/callback` to `$XDG_STATE_HOME/callback`.
- `XDG_CONFIG_HOME`: Moves the settings file from `~/.config/callback/env.json` to `$XDG_CONFIG_HOME/callback/env.json`.

Env var overrides live in `~/.config/callback/env.json`, a settings file
callback owns and reads itself at process startup, independent of any MCP
host's config file. Use `callback config langsmith` or `callback config env
...` to write it, and `callback config status` to inspect it (read-only; also
warns about a legacy `callback` entry left in `~/.claude.json` or
`~/.codex/config.toml` by an old `setup-mcp` install — run `callback
uninstall` to remove it). Restart the MCP host after config changes.

Tracing is opt-in. What a trace contains depends on the span type:

- **Tool spans** (`trace_tool`) send these arguments when present: `session_id`,
  `jd_url`, `jd_raw_text`, `jd_json`, `edits`, `page_ids`, `no_coverage`,
  `resume_label`, `output_dir`. Other arguments (resume and file paths passed to
  the profile tools, story intake, host tags) are not sent. The tool's reply is
  sent as text except for two cuts:
  - `email` and `phone` fields become placeholders anywhere, and email- and
    phone-shaped text is masked inside any string. Name, location, address and
    links become placeholders only inside a structured contact block; a name
    written inside free text or a wiki page is not caught.
  - A fixed set of profile fields is cut when it appears at the top level of a
    reply's `data`: `compiled_profile`, `sections` and `intake` become counts
    and key names, the skill lists (`skills_index`, `orphaned_skills`,
    `skill_coverage_warnings`) become counts, and `primary_skill` and
    `story_id` become `<redacted>`.

  Resume and profile content outside those fields still goes out. That includes
  resume bullet text (`trim_candidates` in the `submit_keywords` reply), the
  wiki index, project page previews (`project_candidates`), score gaps and
  keyword names, pages returned by `get_wiki_pages`, and the `submit_tailor`
  report, which names skills and states the candidate's years of experience.
- **Node spans** (`trace_node`) send lengths, key names, booleans, the two
  page-count numbers, and identifiers (`session_id`, graph and node names,
  status, error stage and code, exception class name). Never content.
- **Decision labels** (`record_decision`) say which path the code took, as span
  metadata, for example `jd_source=pasted`. Labels are booleans or lowercase
  `[a-z0-9_]` tokens, never content. A label set inside a node appears on that
  node's span. A label set in a tool body appears on the tool span and on every
  node span created after it.

API keys never go into a trace. Do not widen what node spans send.

| Label | Values | Meaning |
|---|---|---|
| `jd_source` | `fetched`, `pasted`, `pasted_after_fetch_failed` | Where the job text came from |
| `jd_extraction` | `clean`, `body_text` | Clean extraction, or whole-page text because the extraction was too short |
| `jd_capped` | true/false | Job text was cut at the 16,000-character cap |
| `jd_truncated` | true/false | Headings with no text under them: the page looks cut off |
| `initial_score_source` | `resume_file`, `sections_text`, `none` | Which text the first score was computed from |
| `experience_years` | `computed`, `partial`, `unavailable` | Whether every job entry gave a usable date range |
| `experience_evaluated` | true/false | False means the total was renormalized without ExperienceFit |
| `no_section_headers` | true/false | The resume scored first has no recognized section header: the input may not be a resume |
| `resume_pick` | `only_one`, `first_of_many` | Several resumes registered: the first was used |
| `tailor_attempt` | `first`, `retry_after_error` | `retry_after_error` means the session's last attempt ended in a pipeline error |

`jd_extraction`, `jd_capped` and `jd_truncated` describe the fetched page only.
Ignore them unless `jd_source=fetched`.

Use `callback trace-check` to verify import/auth/project reachability before a demo.
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
- Infrastructure adapters own I/O boundaries: `jd_fetcher.py`, `extractor.py`, `render/`, `wiki.py`, `repository/`, and `version_check.py`.
- Observability adapters live behind `observability.py`; graph code may ask for trace config, but workflow nodes should not know vendor details.

The key boundary: the host owns LLM reasoning and judgment. callback owns state,
validation, deterministic scoring, rendering, ledger recording, and explicit workflow
handoff metadata.

### Two graphs, one server

`server.py` (FastMCP) exposes thirteen tools: eight wired to two distinct LangGraph state graphs, two for search preferences, and three that read and write the application ledger (`ledger.py`):

| Tool | Graph | Behavior |
|---|---|---|
| `load_jd` | apply | Loads JD markdown, resolves a resume label, and returns host extraction instructions. |
| `submit_keywords` | apply | Accepts host-extracted JDData, runs parse/initial score, and returns score gaps plus tailor handoff guidance. |
| `submit_responsibilities` | apply | Optional pass 2: stores the host's `key_responsibilities` list, drops terms already scored, returns the tailor handoff. |
| `submit_tailor` | apply | Applies host edits, resumes the graph, and finalizes the PDF/report artifacts. |
| `get_wiki_pages` | apply | Reads wiki pages for the active resume label. |
| `onboard_user` | profile | Starts profile intake and registers the resume plus optional source files. |
| `compile_profile` | profile | Resumes the profile graph thread (or starts a new one) and returns the recompiled profile with orphaned skills. |
| `create_story` | profile | Persists a behavioral story and returns orphaned skills; recompiles the profile in the same call. |
| `check_update` | utility | Returns current version, latest release tag, and update status. |
| `set_search_preferences` / `get_search_preferences` | utility | Save / read the user's job-search preferences. |
| `find_job` | ledger | Returns whether a posting is already in the ledger, its latest status, and latest `score_before` / `score_after` totals (dedupe); returns its `job_key`; falls back to company + title when the URL misses (weaker match, see `matched_by`; a URL match with a different stored title reports `key_title_mismatch`). A `url` without http(s):// is ignored. |
| `record_status` | ledger | Adds a status event to a job (by URL, company + title, or the `job_key` from `find_job`); creates the job if new; never overwrites history. A `url` without http(s):// (e.g. a recruiter thread) goes into the note and the job is keyed by company + title. |
| `export_ledger` | ledger | Writes the ledger as CSV to an absolute `.csv` path: `mode="jobs"` (default) is one row per job (latest status and scores); `mode="events"` is one row per status event with its own date; `mode="contacts"` is those events kept to EDD-reportable ones (notes starting `Contact method:`, statuses starting `Applied` or `Already applied`) - use for EDD. |

All tools return JSON envelopes via `_ok` / `_err`:
- Success: `{"session_id", "status": "ok", "next_action"?, "data"?, "workflow"?}`
- Error: `{"status": "error", "error": {"stage", "code", "message", "retriable"}, "session_id"?}`

### Agent MCP Playbook

When the user asks to use callback for a job, the host should follow the workflow metadata:

1. Call `load_jd` with `jd_url` or `jd_raw_text`.
2. Extract compact JDData from `data.jd_text` using `data.extraction_protocol`.
3. Call `submit_keywords` with the same `session_id` and the compact `jd_json` string.
   If `workflow.next_tool` is `submit_responsibilities`, start a fresh subagent with exactly `data.responsibilities_protocol` and load_jd's `data.jd_text`, then send its list to `submit_responsibilities`. Skip this if you cannot start a subagent.
4. If `workflow.next_tool` is `get_wiki_pages`, use `data.wiki_index` to fetch relevant evidence pages, then call `submit_tailor`.
5. If `workflow.next_tool` is `submit_tailor`, create honest edits from `data.sections`, `data.score_gap`, wiki evidence, and `data.tailor_instructions`.
6. If `workflow.next_tool` is `onboard_user` or `create_story`, collect the missing profile evidence, compile the profile, then restart the job flow with `load_jd`.
7. After `submit_tailor`, return `data.pdf_path`, `data.ledger_path`, `data.report`, and `data.outcome` to the user.

The host owns keyword extraction and tailoring judgment. callback owns state, validation, rendering, scoring, and ledger recording.

### Apply graph (`apply_graph.py`, `apply_nodes.py`)

Linear graph with host handoff interrupts after `jd_fetch` and `keywords_accept`:

```text
jd_fetch -> keywords_accept -> parse_initial -> score_initial -> tailor -> render
        -> parse_final -> score_final -> report -> finalize -> END
```

`submit_tailor` resumes at `tailor`.

Errors in `tailor`, `render`, `parse_final`, or `finalize` route back to the `tailor` interrupt; `submit_tailor` returns `pipeline_error` with `retriable: true` and may be called again with the same session to retry.

Checkpointer DB: `<temp folder>/callback-<uid>/apply-sessions.db` (`paths.apply_db_path()`; the temp folder is `tempfile.gettempdir()`). Sessions idle more than 24 h are deleted when the DB is opened.
State schema: `ApplyState` in `state.py` (single Pydantic model - entire graph state).
Keyword extraction is host-owned: `load_jd` returns the JD markdown and extraction protocol, then `submit_keywords` stores only validated JDData submitted by the host.

### Profile graph (`profile_graph.py`, `profile_nodes.py`)

Cyclic, with interrupts after `onboard` and before `create_story`:

```text
check_profile ──(resume_path or no profile)──▶ onboard ─▶ compile_profile ─▶ check_orphans
              ├─(story pending in intake)────▶ create_story ─▶ compile_profile ─┘   │
              └─(otherwise)──────────────────▶ compile_profile ─────────────────┘   │
                                                                                     ▼
                              create_story ◀──(orphans)── check_orphans ──(none)──▶ END
```

Interrupts: after `onboard`; before `create_story`. `compile_profile` and `create_story` accept an optional `session_id` to resume the thread; without one they start a new thread that `check_profile` routes to the right node.

`create_story` writes one page, `experience/story-NNN.md`, with YAML frontmatter
(`type`, `title`, `job_title`, `tags`, `story_type`, `timestamp`) and a body of
`# title` then `**Situation:**` / `**Behavior:**` / `**Impact:**` paragraphs.
`compile_profile` reads every story page and rewrites only `index.md` and
`compiled_profile.json` — once the one-time migration has run it never touches a story file, so hand edits to a
story's body survive `compile_profile`. `accomplishments.json` holds only
`onboard_text`; migration of any legacy stories out of the JSON and onto pages
runs automatically at the start of the first `onboard` or `compile_profile`.

Checkpointer DB: `<temp folder>/callback-<uid>/profile-sessions.db` (`paths.profile_db_path()`; the temp folder is `tempfile.gettempdir()`). Sessions idle more than 24 h are deleted when the DB is opened.
State schema: `ProfileState` in `state.py`.

### JD Fetching (`jd_fetcher.py`)

URL fetching uses Playwright plus trafilatura. The fetch surface is controlled by:
- `CALLBACK_FETCH_PAGE_TIMEOUT_MS`
- `CALLBACK_FETCH_OUTER_TIMEOUT_S`
- `CALLBACK_FETCH_SETTLE_BUDGET_S`

`jd_fetch` loads the page with Playwright (Chrome user agent, `domcontentloaded` plus a content-aware settle — body text polled until stable after a ~2.5 s minimum window, or the settle budget elapses), extracts markdown with trafilatura, falls back to body text when the extraction is thin (and rejects a page that is still under 1,200 characters as `fetch_thin`), and caps `jd_text` at 16,000 characters (about 4,000 tokens), logging `fetch_oversized`. A non-2xx status raises and is logged as `fetch_status`.

Do not add a silent fallback path if URL fetch fails.

### Scoring (`scorer.py`)

Pure deterministic Python - no I/O, no LLM calls.

| Dimension | Max | Signal |
|---|---|---|
| KeywordMatch | 55 | Required (0.7) + preferred (0.3) keywords |
| ExperienceFit | 15 | Years met (years-only; `None` + renormalization when not evaluable) |
| ImpactEvidence | 10 | Quantified metric bullets |
| ATSFormat | 10 | Standard section headers present |
| Readability | 10 | Absence of filler phrases |

### Rendering (`render/`)

PDF rendering uses HTML + Playwright in `callback/render/html_builder.py`.

### Evals (`evals/`)

Three evals, no framework. `extract_checks.py` (E1) and `tailor_checks.py` (E2)
are pure functions over a host output and a fixture; `test_compile.py` (E3)
runs the real `compile_profile` node on a staged copy of a case. Every fixture
is committed under `evals/{extract,tailor,compile}/`: public job postings for
extract, and two invented profiles — Jane Doe and the larger Morgan Reyes —
covering tailor and compile. Nothing here is personal data.
`scripts/run_evals.py` is the only code that calls a model: it shells out to
`claude -p`, `codex exec`, or `hermes chat`, isolated with `--strict-mcp-config` and an empty
`--mcp-config`, `--tools ""`, `--setting-sources ""`, and a scratch working
directory for Claude (`--bare` is avoided because it disables keychain auth),
and `--ignore-user-config` for Codex (so `$CODEX_HOME/config.toml` — and any
MCP servers or instructions it configures — can't leak into the run). Hermes uses
`--safe-mode` to disable personal customizations but may retain built-in tools.
The runner reads only saved model choices (and Hermes's model provider) before
launching isolated commands, so `--model` is optional for these three harnesses.
Ollama and llama.cpp use direct loopback HTTP chat requests and require `--model`;
`--port` overrides defaults 11434 and 8080 respectively. `--provider` is a Hermes
override. Fresh calls and saved-output checks are logged explicitly. The runner saves
the reply next to the fixture (`<board>.host.json`, `<case>/host.json`), runs
the checks, prints one table, and records the run as a LangSmith experiment
named `<commit>-<host>-<model>` when `LANGSMITH_API_KEY` is set. CI never
calls a model; tests that read host outputs are marked `local`.

With `LANGSMITH_API_KEY` set, the runner uploads every fixture's inputs (JD
text, sections, keywords, wiki pages) and outputs to LangSmith — all of it is
committed and public, so there is nothing to withhold.

### Module map

| Module | Role |
|---|---|
| `server.py` | FastMCP tool definitions, envelope helpers, structured JSON logging |
| `apply_graph.py` | `get_apply_graph()` cached accessor; linear apply pipeline with host handoff interrupts and error routing |
| `apply_nodes.py` | Apply nodes (`jd_fetch`, `keywords_accept`, `parse_initial`, `score_initial`, `tailor`, `render`, `parse_final`, `score_final`, `report`, `finalize`) |
| `profile_graph.py` | `get_profile_graph()` cached accessor; cyclic profile graph with router edges and interrupts |
| `profile_nodes.py` | Profile nodes (`check_profile`, `onboard`, `compile_profile`, `check_orphans`, `create_story`) |
| `state.py` | `ApplyState`, `ProfileState`, and related profile data models |
| `scorer.py` | Deterministic ATS scorer |
| `jd_data.py` | JD JSON schema, extraction protocol, and validators |
| `jd_fetcher.py` | Playwright + trafilatura job-description fetcher |
| `extractor.py` | Resume text extraction (PDF, DOCX, TXT, Markdown/plain text) |
| `section_map.py` | Resume section editing helpers |
| `wiki.py` | Wiki storage for resume-linked behavioral stories |
| `repository/` | Resume, onboard text, and story-page persistence |
| `repository/stories.py` | Story pages: read, write, migrate legacy JSON stories to OKF pages |
| `profilecompiler.py` | `compile_profile()` function |
| `wikirenderer.py` | Renders `index.md` |
| `render/` | HTML + Playwright resume rendering |
| `paths.py` | Every data directory and the atomic writers |
| `ledger.py` | Global application ledger in SQLite (`paths.ledger_path()`): jobs, runs, append-only status events |
| `cli.py` | `callback` CLI entry point |
| `plugin_install.py` | Plugin installation functions (replaces `HarnessTarget` dataclass) |
| `ledger_import.py` | One-time, re-runnable import of old run archives, the record CSV, and the old contact ledger into the ledger |
| `observability.py` | Trace config port and LangSmith adapter |
| `version_check.py` | Current-vs-latest release comparison |
| `evals/` | Eval checks, fixtures, runner; see Evals |

## Change Discipline

- Touch only what the current task requires.
- New scoring heuristics must map to a real ATS gate mechanism and stay deterministic.
- Scoring weights live in config - don't hardcode them.
- All fallbacks must be explicit, logged, and approved.
- Don't add complexity beyond the walking skeleton. When tempted toward pgvector, LLM-as-judge, provider clients, RAG, or an eval harness, stop unless there is an explicit OpenSpec proposal for it.
- Do not move keyword extraction, evidence selection, or resume-tailoring judgment into callback server-side LLM calls unless explicitly requested through a proposal.
- Do not organize new work as MVC/MVVM. Use the workflow-first ports-and-adapters pattern above.
- Active design proposals live in `openspec/changes/`. Check there before redesigning a graph.
