# INTENT.md — callback

What this project is for, what it is not for, and what we intend to change next.
`BRIEF.md` records the original charter. `DECISIONS.md` records why the architecture
looks the way it does. `EPICS.md` records what shipped. This file records intent going
forward and feeds the roadmap. Update it when intent changes, not when code changes.

Last audit: 2026-09-03 (ponytail audit + correctness + architecture pass).
Baseline at audit: v1.4.1, 587 tests passing, ruff and pyright clean, 147 runtime packages.

---

## North star

Get the user past the ATS gate so they talk to a human recruiter.

Every change is judged by one question: does it make the tailored resume more
retrievable by a recruiter's search, or more survivable in the recruiter's skim,
without misrepresenting the candidate? If not, it does not ship.

## Why callback exists (the second job)

A portfolio piece proving stateful-agent design with LangGraph: a checkpointed graph
that pauses at explicit host handoff points across separate MCP calls. The apply graph
is that proof. Anything that weakens the proof (decorative graphs, stubs pretending to
be graphs) works against the intent even if it works as code.

## The profile is the source of truth

Tailoring may only use evidence that exists in the profile wiki. The wiki follows the
Open Knowledge Format (OKF v0.1, Google's formalization of Karpathy's LLM-wiki pattern):
a directory of markdown files with YAML frontmatter, one concept per file, the file path
as the concept's identity, plain markdown links between files, and `index.md` for
progressive disclosure. The only required frontmatter field is `type`.

Consequences:

- The markdown files are the original. JSON is a cache that compile rebuilds from them.
  Today it is the reverse, which is why hand edits get clobbered (see W2, M2.5).
- Metadata is declared in frontmatter, never scraped from prose.
- A human, an editor, git, or another agent may edit a wiki file and callback must
  respect the edit on the next compile.

Data flow, before and after: https://claude.ai/code/artifact/49338a2d-dca0-4ab7-922a-0ebcd918c0b2

## Non-goals

- No LLM calls inside the server. The host owns reasoning; the server owns state,
  scoring, rendering, and persistence.
- No multi-user, no remote transport, no auth. Single user, stdio, local disk.
- No vendor ATS emulation. The score predicts retrievability and skim survival, nothing more.
- No pgvector, RAG, or LLM-as-judge unless a written proposal in `openspec/changes/`
  ties it to the north star.
- No eval framework. Evals are fixtures plus pytest plus one runner script (see M6).
  If that stops being enough, write a proposal first.
- No multi-resume registry. One resume labeled `primary`. Plumbing for more is dead weight.

## Operating principles

1. Honest signal only. Never fabricate experience, skills, or metrics. Never keyword-stuff.
2. Deterministic scoring. Same inputs, same score. Weights live in `ScoringConfig` only.
3. No silent failures, no hidden fallbacks. Every fallback is logged and approved.
4. Trust boundaries are hard. JD text is untrusted web content that reaches the host
   LLM before the host calls back into the server. Validate every host-supplied path and id.
5. Lazy by default. Stdlib before dependency, existing helper before new helper, delete
   before add. Finite maintenance horizon: build only what the walking skeleton needs.

## Current state (2026-09-03)

Working end to end: `load_jd → submit_keywords → get_wiki_pages → submit_tailor` produces
a scored, rendered, archived PDF. Profile onboarding works for a first resume.

Known defects, verified by running code:

| # | Severity | Defect | Where |
|---|----------|--------|-------|
| D1 | High | `get_wiki_pages` page ids are not confined to the wiki root; `../../x` reads any readable file and returns it to the host | `callback/wiki.py:430` |
| D2 | High | Re-onboarding with an existing profile skips the `onboard` node; crashes if orphans exist, silently no-ops otherwise | `callback/profile_graph.py:51` |
| D3 | Med | Every log line is written to `server.log` twice | `callback/server.py:109` |
| D4 | Med | A render failure ends the graph; retrying `submit_tailor` returns `invalid_state`; only recovery is restarting from `load_jd` | `callback/apply_graph.py:768` |
| D5 | Med | `XDG_DATA_HOME` honored by four stores, ignored by wiki, both checkpoint DBs, and applications dir | `callback/wiki.py`, `apply_graph.py`, `profile_graph.py`, `apply_nodes.py` |
| D6 | Low | A bare year range in the resume header is captured as the phone number | `callback/extractor.py:735` |
| D7 | Low | Extractor errors escape `submit_keywords` / `submit_tailor` as raw MCP failures instead of the envelope | `callback/server.py` |
| D8 | Low | `_dump_toml` rewrites all of `~/.codex/config.toml`, drops comments, raises on arrays of tables | `callback/cli.py:215` |

Known weight (works, but costs more than it earns):

| # | Kind | What | Est. cut |
|---|------|------|----------|
| W1 | dep | crawl4ai: 93 of 147 runtime packages and 2.0 s of import time to fetch one page; Playwright is already installed. Its pruning also produced the 48,000-token JD outlier | 1 dep, ~87 packages (trafilatura adds 6) |
| W2 | arch | Profile graph is decorative; `compile_profile` and `create_story` bypass it. Wiki markdown is a render of `accomplishments.json`, so hand edits are overwritten; story metadata is regex-scraped from prose (`server.py:255`) | make the graph real (see M2, M2.5) |
| W3 | dep | dataclass-wizard for JDData; pydantic already present | 1 dep, ~40 lines |
| W4 | dup | 8 near-identical Claude/Codex env functions in `cli.py` | ~80 lines |
| W5 | dead | Multi-resume plumbing (`ambiguous_resume`, `resume_label` param) unreachable | ~30 lines |
| W6 | dup | 4 copies of `data_dir()`, 3 copies of atomic JSON write | ~40 lines, fixes D5 |
| W7 | dep | rapidfuzz (one warning string), pypdf (page count only), httpx (one GET) | 3 deps |
| W8 | yagni | `HarnessTarget` dataclass + injectable runner for 2 targets; `ProfileCompiler` and `WikiRenderer` classes with no state | ~90 lines |
| W9 | dead | `ProfileState.wiki_path/error`, `TailoredResume.volunteer_raw`, `ApplyState.finalized`, `WikiStore.read_index`, `main.py`, dormant `[tool.ruff.lint.pylint]` block | ~30 lines |
| W10 | dup | 3 copies of flatten-skills; `apply_nodes._normalize_for_match` duplicates scorer's; `outcome` computed twice | ~30 lines |
| W11 | size | `observability.py` (465 lines) exceeds both graphs combined; `cli.py` (1,103 lines) is 17% of the codebase | judgment call |
| W12 | perf | `build_apply_graph()` per tool call opens a new SQLite connection and never closes it | singleton |

## Intended direction (roadmap inputs)

Ordered by dependency and payoff. Each milestone is one PR to `main` and leaves the
suite green. Estimates are for one person.

Order: M1 → M2 → M2.5 → M6 → M3 → M7 → M4 → M5. Evals come before the fetcher swap and
the token diet so both are measured against something.

### M1 — Close the trust boundary (half a day)

Ships: D1, D2, D3, D6, D7.
Done when: a test proves `../` page ids are rejected, a test proves re-onboarding with
an existing profile replaces the resume, `server.log` has one line per event.

### M2 — Make the graphs honest (one to two days)

Ships: W12, D4, and the graph half of W2.
Done when: `compile_profile` and `create_story` resume the checkpointed profile graph
thread instead of calling nodes directly, so the `check_orphans → create_story →
compile_profile` cycle actually runs; the apply graph is built once per process; a
failed render leaves the session waiting at the tailor interrupt so `submit_tailor`
can be retried.

### M2.5 — OKF conformance for the profile wiki (one to two days)

Ships: the data half of W2.
Spec: the diagram linked above. In short:

1. `create_story` writes one `experience/story-NNN.md` with frontmatter
   (`type: story | project`, `title`, `job_title`, `tags`, `timestamp`) and the
   situation / behavior / impact as body. It never writes `accomplishments.json`.
2. `compile_profile` reads every `experience/*.md` (split on the `---` fence,
   `yaml.safe_load` the header; PyYAML is already installed under langchain), rebuilds
   `index.md` and `compiled_profile.json`, and never rewrites a story file.
3. `submit_keywords` reads `type` and `tags` from frontmatter; the three regex scrapers
   in `server.py` (`_project_story_name`, `_project_story_skills`, `_is_project_story`)
   are deleted.
4. A one-time migration writes frontmatter onto the existing 14 story files from
   `accomplishments.json`, then `accomplishments.json` keeps only `onboard_text`.

Out of scope for this milestone: converting `sections.json` (the resume) to markdown,
`log.md`, per-folder `index.md`. Revisit after M6 shows what the evals need.

Done when: every wiki file has frontmatter with `type`; a hand edit to a story body
survives `compile_profile`; compiling the 14 existing stories produces an `index.md`
identical to today's; no regex reads story metadata anywhere in `callback/`.

### M3 — Replace the fetcher (half a day plus smoke runs)

Ships: W1.
Measured 2026-09-03 on five archived JD URLs: Playwright plus trafilatura matched
crawl4ai's keyword recall on every live page (within one term), returned 1.5x to 37x
fewer tokens (the 48,000-token outlier was crawl4ai failing to prune Qualcomm's page),
and fetched in 2.7 to 4.1 s. The one bot-check failure was caused by the default
headless user-agent string, not by the absence of crawl4ai's stealth mode; a normal
Chrome user agent fixed it and playwright-stealth changed nothing.

Spec:

1. `jd_fetcher` uses Playwright (already required for rendering) with a normal Chrome
   user-agent string and a 1280×900 viewport.
2. Wait strategy: `domcontentloaded` plus a 2.5 s settle. Network idle timed out on one
   host and doubled fetch time on another for identical recall.
3. Extraction: `trafilatura.extract(html, output_format="markdown", favor_recall=True,
   include_tables=True)`, imported lazily inside the fetch. If the result is under 300
   tokens, fall back to the page's body text so a thin extraction is not mistaken for an
   empty page.
4. Hard cap `jd_text` at 4,000 tokens (about 16,000 characters). Truncate and log
   `fetch_oversized` with the original size.
5. crawl4ai and its env vars (`CALLBACK_FETCH_MAGIC`, `CALLBACK_FETCH_WAIT_UNTIL`) are
   removed. Keep the page and outer timeouts.

Done when: crawl4ai is out of `pyproject.toml`; the five measured URLs (Qualcomm, Apple,
Ashby, Cedar, Greenhouse) are E1 fetch fixtures with their archived keywords as the
recall golden; `scripts/smoke_apply.py` passes on three of them; server import time drops
by at least 1.5 s.

Out of scope: LinkedIn login walls and Cloudflare challenge pages. Those remain
"paste the text" for both fetchers.

### M4 — Shed weight (one day, mechanical)

Ships: W3, W5, W6, W7, W8, W9, W10, D5, D8.
Done when: `pyproject.toml` lists at most 11 runtime dependencies, one `paths.py` owns
every data directory, and enabling `PLR09` in ruff either passes or the block is removed.

### M5 — Shrink the plumbing (judgment, one day)

Ships: W4, W11, plus the resolutions of Q3 and Q4.
Done when: `setup-mcp` is removed; the build-version stamp (`setup.py` hook,
`scripts/build-version.sh`, `_build_info.py`, `cli._read_build_version`) is removed;
`.mcp.json` launches the server from `${CLAUDE_PLUGIN_ROOT}`; `claude --plugin-dir .`
runs the local server and skills together; `cli.py` is under 600 lines; and
`observability.py` sanitizes without the exception sentinel round trip.

### M6 — Evals: is the LLM doing its job? (two to three days)

Three of the pipeline's steps depend on someone doing honest work. Two of them are the
host LLM. One is Python. Each gets an eval that fails loudly when the work is wrong.

| Eval | Who does the work | Fixture in | Checks (all deterministic) |
|------|-------------------|------------|----------------------------|
| E1 keyword extraction | host LLM, via `EXTRACTION_PROTOCOL` | `evals/extract/<jd>.md` + `<jd>.golden.json` | precision and recall of `required`, `preferred`, and OR-groups against the golden JDData; terms must be exact JD substrings (no paraphrase); `required_years` and `title` exact |
| E2 tailoring | host LLM, via `_TAILOR_INSTRUCTIONS` and the `tailor-resume` skill | `evals/tailor/<case>/` with sections, wiki pages, keywords, and a `constraints.json` | every added skill appears in a dated bullet; every edit's nouns and numbers are grounded in the source resume or the supplied wiki pages (substring or fuzzy match, threshold in `constraints.json`); no banned verbs or phrases; `score_final.total >= score_initial.total`; no edits rejected by `apply_edit` |
| E3 compile | Python (`compile_profile`) | `evals/compile/stories/*.md` + `golden/index.md` + `golden/compiled_profile.json` | byte-identical `index.md`; identical `skills_index` and `orphaned_skills`; a story with a hand-edited body round-trips unchanged |

Mechanics, kept minimal on purpose:

- E3 is plain pytest and runs in CI.
- E1 and E2 need a live host model. One runner script, `scripts/run_evals.py`, feeds
  each fixture to the host (`claude -p` or `codex exec`, model chosen by flag, default
  the model used for tailoring today) and writes the host output next to the fixture.
  The deterministic checks then run as pytest marked `local`. CI does not call a model.
- Every runner invocation is also recorded as a LangSmith experiment: the fixtures are
  uploaded once as a dataset, the checks above are the evaluators, and
  `langsmith.evaluate` gets the run name from the git short hash and the model flag.
  Fixture files in git stay the source of truth; LangSmith holds the history so two
  commits or two models can be compared side by side without a local diff.
- Fixtures are real: at least 5 JDs across two boards for E1 (one with OR-groups, one
  with no labeled sections), at least 3 tailoring cases for E2 (one where the honest
  answer is `no_coverage`), and the user's own 14 stories for E3.
- A run prints one table: eval, fixture, pass/fail, and the first failing check. No
  dashboards, no history store. Diff the committed host outputs in git to see drift.

Done when: `uv run pytest evals/` passes for E3 in CI; `uv run python scripts/run_evals.py`
followed by `uv run pytest -m local evals/` passes for E1 and E2 on the chosen host
model; a deliberately keyword-stuffed tailoring output fails E2.

### M7 — Token diet (one day)

Measured 2026-09-03 against the real profile and the last 285 applications. The host
reads about 10,000 tokens of tool output per median job; the p90 JD pushes that to
15,500. Every Python step together runs under 2 s except the fetch, so wall-clock time
is host thinking time, and tokens are the lever.

| Step | Tokens today | What it is |
|------|-------------:|------------|
| load_jd | 2,700 | JD text 1,950 + extraction protocol 750 |
| submit_keywords | 5,700 | sections 1,479, trim candidates 1,298, wiki index 1,256, project candidates and recommendations 950, tailor instructions 338, keywords and gaps 300 |
| get_wiki_pages | 1,200 | 3 pages at 393 (median) |
| submit_tailor | 400 | report |

Items, ranked by payoff:

1. **Trim candidates restate the resume.** Return the bottom 3 by score as target and
   score only, no text. The text is already in `sections`. Saves ~1,100 per job.
2. **Inline the top evidence pages.** Project candidates are already ranked
   deterministically. Return the top 3 page bodies inside `submit_keywords` and make
   `get_wiki_pages` optional for the rest. Removes one host round trip (10 to 30 s per
   job). Logs show the host calls `get_wiki_pages` on only 23% of runs today, so most
   tailoring happens without evidence; inlining fixes that as a side effect.
3. **Cap the JD.** Covered by M3 item 4. Removes the 48,000-token outlier and trims the
   40 of 171 URL fetches that came back over 5,000 tokens.
4. **Deduplicate the candidate object.** The top candidate appears three times: in the
   list, in `project_swap_recommendation`, and in `project_layout_recommendation`.
   Reference it by `page_id`. Saves ~300.
5. **Move the extraction protocol into the `submit_keywords` tool description.** The
   server owns it, so it stays in step with the JDData schema; Claude Code loads MCP
   schemas on first use, so idle sessions pay nothing. Saves 750 per job only in
   multi-job sessions (the auto-apply loop); a single-job session pays the same either
   way because a tool result also stays in the transcript. Codex may not defer schemas,
   so there it is a fixed 750 cached tokens per turn. Keep `tailor_instructions` in the
   payload: they carry the contract the server enforces (added skills must appear in a
   dated bullet, the context-line format, project swap rules) and the skill does not
   duplicate them. Trim the skill's own banned-word list to a pointer instead.

Done when: a median job reads at most 6,500 tokens of tool output (measure with the
E1/E2 fixtures); a run that tailors with evidence needs three MCP calls, not four; the
per-step table above is re-measured and updated in this file.

## Open decisions

Each blocks a milestone. Answer here, then move the answer to `DECISIONS.md`.

- **Q1 (resolved 2026-09-03):** Keep the profile graph and make it real. The profile is
  the source of truth for tailoring, and once the wiki files are the original (M2.5) the
  compile cycle has honest work to loop over.
- **Q2 (resolved 2026-09-03):** Replace crawl4ai with Playwright plus trafilatura.
  Measured equal recall, far fewer tokens, and the bot-check failure was the user-agent
  string, not stealth mode. See M3.
- **Q3 (resolved 2026-09-03):** Drop `setup-mcp`. Plugin install is the path more
  harnesses are adopting. `config env` and `config langsmith` stay until M5 decides
  whether the plugin's own env handling covers them.
- **Q4 (resolved 2026-09-03):** Delete the build-version stamp. Local development runs
  the plugin straight from the working tree with `claude --plugin-dir .`, and the
  plugin's `.mcp.json` should launch the server from `${CLAUDE_PLUGIN_ROOT}` (via
  `uv run --project`) instead of `uvx --from git+https://...`, so the server and the
  skills always come from the same checkout. That also closes a drift risk: today an
  installed plugin runs skills from the plugin cache but the server from git `main`.
  "Which commit am I running" becomes `git rev-parse HEAD` in the worktree.
- **Q5 (resolved 2026-09-03):** Purpose of the evals, in order: (1) catch regressions
  from our own changes, (2) later, prove a cheaper model still passes. Default model is
  the one used for tailoring today. Fixture files in git are the source of truth; each
  run is also recorded as a LangSmith experiment (dataset + custom evaluators via
  `langsmith.evaluate`, SDK already installed) so run-over-run comparison lives in the
  LangSmith UI. Local pytest remains the gate; LangSmith is the history.

## What we will not do in this cycle

- Add scoring dimensions. The rubric is stable; new heuristics need an ATS-mechanism
  justification and go through `openspec/changes/`.
- Touch the tailor instructions or extraction protocol. They are prompt contracts with
  the host skills; changing them is a separate, tested change.
- Add a second transport or a web UI.
