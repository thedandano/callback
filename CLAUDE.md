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

# One-time browser setup (job-description fetching and PDF rendering)
uv run playwright install chromium

# Run the MCP server (stdio)
uv run python -m callback.server

# Configure tracing env vars in callback's own settings file (~/.config/callback/env.json)
uv run callback config langsmith
uv run callback config status
uv run callback config env list
uv run callback config env set CALLBACK_TRACE_BACKEND langsmith
uv run callback config env unset CALLBACK_TRACE_BACKEND
uv run callback trace-check
uv run callback trace-check --emit-test-trace

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
uv run python scripts/run_evals.py --checks-only       # re-check saved outputs, no model call, no LangSmith upload
uv run pytest -m local evals/                          # E1 + E2 checks over the saved host outputs
# baseline 2026-09-07, claude default model: E1 2/6 (PASS cedar/reddit), E2 1/8 (see INTENT §M6)
# updated 2026-09-13, claude default model: E1 4/6 (PASS apple/cedar/qualcomm/reddit) after
# fixing 4 broken answer keys and a fetch bug (see plan problem-the-model-keeps-hashed-mccarthy.md).
# Remaining E1 failures are genuine model-judgment calls, not fixture defects: ashby left one
# "X or Y" bullet as two flat preferred terms instead of an OR-group; greenhouse described part
# of the JD as key_responsibilities prose instead of atomic required keywords.
# updated 2026-09-13 (round 2), claude default model: E1 3/6 (PASS cedar/qualcomm/reddit) after
# sharpening the OR-group protocol rule and closing an eval blind spot that let a model inflate
# keyword coverage by collapsing independent terms into one OR-group (see the same plan, M7-M9).
# Remaining failures, all genuine model-judgment gaps: apple over-applied the slash-disjunction
# signal to two compound job-function names ("personalization / recommendation / ranking",
# "notification / message-delivery systems") that aren't real either-or alternatives; ashby
# paraphrased and dropped several required terms/one OR-group in this run (see the sample-to-
# sample variance note below); greenhouse still under-extracts from unlabeled prose. Sampling
# variance is real and material here - the same protocol scored ashby 4/6-worthy on one run and
# missed 16 terms on the next; a single live run is one data point, not a verdict. Comparison run
# on Codex gpt-5.6-terra: E1 2/6 (PASS qualcomm/reddit) on the same fixtures and rubric.
# updated 2026-09-15 (round 3), claude default model: E1 2/6 (PASS qualcomm/reddit) after three
# small protocol fixes: an "(e.g., X, Y, Z)" disjunction signal, a generalizable slash test
# ("would just ONE alone satisfy this?") replacing a fixed compound-term carve-out list, and a
# worked example for unlabeled bolded-header prose (see the plan, M10-M11). This run is a stark
# illustration of the variance already flagged above: cedar - which had passed in EVERY prior
# run across all three rounds - failed by dumping all 5 preferred_any groups as flat terms, and
# apple's atomization broke down wholesale (whole clauses kept intact instead of split). Root-
# caused before recording: re-ran cedar against the UNCHANGED pre-round-3 protocol and got the
# identical failure, twice - so this is not a regression from the round-3 wording, it's the same
# live model producing a much lower-quality extraction on this occasion. Treat any single E1
# number as noisy; the checks themselves (verified via the guard test and unit tests) are the
# reliable part. Comparison run on Codex gpt-5.6-terra: E1 3/6 (PASS greenhouse/qualcomm/reddit) -
# its best result yet, and the first time either model has passed greenhouse.
# updated 2026-09-15 (M12), claude default model: E1 2/6 (PASS qualcomm/reddit) after a manual
# review of all 6 fixtures in an HTML audit tool surfaced one real gap: a stated requirement
# illustrated by exactly ONE example via "(e.g., X)" was being treated as two requirements (apple's
# "a big-data framework (e.g., Apache Spark)" pulled in "Apache Spark" as its own required term).
# Added a rule-2-scoped clause distinguishing this from rule 4's unlabeled-prose extraction (where
# a named example, e.g. greenhouse's "technologies like CDC", is still a real signal worth keeping)
# and dropped "Apache Spark" from apple's answer key. Verified fixed in this run's raw host output.
# This run's failures are the same documented sampling variance, not new gaps: ashby and cedar
# under-atomized (broad phrases like "SQL & NoSQL datastores" instead of split terms, all 3
# required_any groups collapsed for cedar); apple and greenhouse still under-extract for reasons
# already on file. Reviewer also flagged ashby's answer key itself contains non-atomic clause
# fragments (e.g. "ML models from research or prototype stage into production at scale") inherited
# from the M8 rebuild - logged as a follow-up answer-key audit, not fixed here.

```

## Env Vars

- `XDG_DATA_HOME`: Moves the whole data root (resumes, wiki, compiled profile, applications archive) from `~/.local/share/callback` to `$XDG_DATA_HOME/callback`.
- `XDG_STATE_HOME`: Moves the state root (session checkpoint DBs, server log) from `~/.local/state/callback` to `$XDG_STATE_HOME/callback`.
- `XDG_CONFIG_HOME`: Moves the settings file from `~/.config/callback/env.json` to `$XDG_CONFIG_HOME/callback/env.json`.
- `CALLBACK_APPS_DIR`: Override where application PDFs and JSON archives are written; overrides only the archive directory, not the other data roots. `submit_tailor`'s `output_dir` argument overrides this per-call for both the PDF and the JSON archive.
- `CALLBACK_FETCH_PAGE_TIMEOUT_MS`: Override the Playwright page-load timeout in milliseconds. Default: `30000`.
- `CALLBACK_FETCH_OUTER_TIMEOUT_S`: Override the outer fetch timeout in seconds. Default: `35`.
- `CALLBACK_TRACE_BACKEND`: Optional tracing backend. Set to `langsmith` to enable LangSmith tracing.
- `LANGSMITH_TRACING`: Must be `true` when `CALLBACK_TRACE_BACKEND=langsmith`.
- `LANGSMITH_ENDPOINT`: LangSmith API endpoint. Defaults to `https://api.smith.langchain.com`.
- `LANGSMITH_API_KEY`: Required for LangSmith tracing; also gates eval experiment recording. The runner logs a WARNING and skips recording when unset.
- `LANGSMITH_PROJECT`: LangSmith project name. Defaults to `Callback` when tracing is enabled.

Env var overrides live in `~/.config/callback/env.json`, a settings file
callback owns and reads itself at process startup — not in any MCP host's
config file. Use `callback config langsmith` or `callback config env ...` to
write it, and `callback config status` to inspect it (read-only; also warns if
a legacy `callback` entry is still sitting in `~/.claude.json` or
`~/.codex/config.toml` from an old `setup-mcp` install — run `callback
uninstall` to remove it). Restart the MCP host after config changes, since it
only reloads env vars at startup.
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
| `compile_profile`| profile  | Resumes the profile graph thread (or starts a new one) and returns the recompiled profile with orphaned skills. |
| `create_story`   | profile  | Persists a behavioral story and returns orphaned skills; recompiles the profile in the same call.      |
| `check_update`   | utility  | Returns current version, latest release tag, and update status. |

All tools return JSON envelopes via `_ok` / `_err`:
- Success: `{"session_id", "status": "ok", "next_action"?, "data"?, "workflow"?}`
- Error: `{"status": "error", "error": {"stage", "code", "message", "retriable"}, "session_id"?}`

### Agent MCP Playbook

When the user asks to use callback for a job, call `load_jd`, extract JDData as the host, call `submit_keywords`, follow `workflow.next_tool`, and finish with `submit_tailor`. Return `data.pdf_path`, `data.archive_path`, `data.report`, and `data.outcome` to the user. If `workflow.next_tool` is `onboard_user` or `create_story`, collect the missing profile evidence, compile the profile, then restart the job flow with `load_jd`.

If you run in a sandboxed filesystem, callback's default output (`~/.local/share/callback/applications/`) is outside your reach. Before calling `submit_tailor`, ask the user for a full output directory inside your sandbox and pass it as `output_dir`; the final PDF (`data.pdf_path`) and the JSON archive (`data.archive_path`) are then both written there directly.

### Apply graph (`apply_graph.py`, `apply_nodes.py`)

Linear graph with host handoff interrupts after `jd_fetch` and before `tailor`:

```
jd_fetch → keywords_accept → parse_initial → score_initial → tailor → render
        → parse_final → score_final → report → finalize → END
```

Errors in `tailor`, `render`, `parse_final`, or `finalize` route back to the `tailor` interrupt; `submit_tailor` returns `pipeline_error` with `retriable: true` and may be called again with the same session to retry.
`jd_fetch` loads the page with Playwright (Chrome user agent, `domcontentloaded` plus a 2.5 s settle), extracts markdown with trafilatura, falls back to body text when the extraction is thin (and rejects a page that is still under 1,200 characters as `fetch_thin`), and caps `jd_text` at 16,000 characters (about 4,000 tokens), logging `fetch_oversized`.

Checkpointer DB: `~/.local/state/callback/apply-sessions.db` (or `$XDG_STATE_HOME/callback/apply-sessions.db` if `XDG_STATE_HOME` is set). An older DB found at the previous location, `~/.local/share/callback/apply-sessions.db` (or `$XDG_DATA_HOME` equivalent), is migrated in place on first use.
State schema: `ApplyState` in `state.py` (single Pydantic model — entire graph state).
Keyword extraction is host-owned: `callback` returns the JD markdown and extraction protocol, then stores only validated JDData submitted by the host.

### Profile graph (`profile_graph.py`, `profile_nodes.py`)

Cyclic, with interrupts after `onboard` and before `create_story`:

```
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

Checkpointer DB: `~/.local/state/callback/profile-sessions.db` (or `$XDG_STATE_HOME/callback/profile-sessions.db` if `XDG_STATE_HOME` is set). An older DB found at the previous location, `~/.local/share/callback/profile-sessions.db` (or `$XDG_DATA_HOME` equivalent), is migrated in place on first use.
State schema: `ProfileState` in `state.py`.

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

### Evals (`evals/`)

Three evals, no framework. `extract_checks.py` (E1) and `tailor_checks.py` (E2)
are pure functions over a host output and a fixture; `test_compile.py` (E3)
runs the real `compile_profile` node on a staged copy of a case. Every fixture
is committed under `evals/{extract,tailor,compile}/`: public job postings for
extract, and two invented profiles — Jane Doe and the larger Morgan Reyes —
covering tailor and compile. Nothing here is personal data.
`scripts/run_evals.py` is the only code that calls a model: it shells out to
`claude -p` or `codex exec`, isolated with `--strict-mcp-config` and an empty
`--mcp-config`, `--tools ""`, `--setting-sources ""`, and a scratch working
directory for Claude (`--bare` is avoided because it disables keychain auth),
and `--ignore-user-config` for Codex (so `$CODEX_HOME/config.toml` — and any
MCP servers or instructions it configures — can't leak into the run); it saves
the reply next to the fixture (`<board>.host.json`, `<case>/host.json`), runs
the checks, prints one table, and records the run as a LangSmith experiment
named `<commit>-<host>-<model>` when `LANGSMITH_API_KEY` is set. CI never
calls a model; tests that read host outputs are marked `local`.

With `LANGSMITH_API_KEY` set, the runner uploads every fixture's inputs (JD
text, sections, keywords, wiki pages) and outputs to LangSmith — all of it is
committed and public, so there is nothing to withhold.

### Module map

| Module               | Role |
|----------------------|------|
| `server.py`          | FastMCP tool definitions; envelope helpers (`_ok`/`_err`); structured stderr JSON logging |
| `apply_graph.py`     | `get_apply_graph()` cached accessor; linear apply pipeline with host handoff interrupts and error routing |
| `apply_nodes.py`     | 10 apply nodes (`jd_fetch`, `keywords_accept`, `parse_initial`, `score_initial`, `tailor`, `render`, `parse_final`, `score_final`, `report`, `finalize`) |
| `profile_graph.py`   | `get_profile_graph()` cached accessor; cyclic profile graph with router edges and interrupts |
| `profile_nodes.py`   | Profile nodes (`check_profile`, `onboard`, `compile_profile`, `check_orphans`, `create_story`) |
| `state.py`           | `ApplyState`, `ProfileState` — Pydantic schemas for each graph |
| `scorer.py`          | Deterministic ATS scorer (no I/O, no LLM) |
| `extractor.py`       | Resume text extraction (PDF via pdfplumber, DOCX via python-docx, TXT) |
| `repository/`        | Resume, onboard text, and story-page persistence |
| `repository/stories.py` | Story pages: read, write, migrate legacy JSON stories to OKF pages |
| `wikirenderer.py`    | Renders `index.md` |
| `paths.py`           | Every data directory and the atomic writers |
| `observability.py`   | Trace config port and LangSmith adapter |
| `evals/`             | Eval checks, fixtures, runner; see Evals |

## Change Discipline

- Touch only what the current task requires.
- New scoring heuristics must map to a real ATS gate mechanism (see Scoring) and stay deterministic.
- Scoring weights and thresholds live in `ScoringConfig` (`scorer.py`) — change them there; never scatter new hardcoded weights.
- All fallbacks must be explicit, logged, and approved.
- Don't add complexity beyond the walking skeleton (see `BRIEF.md`). When tempted toward pgvector / LLM-as-judge / eval harness before the graph runs end-to-end, stop.
- Active design proposals live in `openspec/changes/`. Check there before redesigning a graph.
