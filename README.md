# callback

[![CI](https://github.com/thedandano/callback/actions/workflows/ci.yml/badge.svg)](https://github.com/thedandano/callback/actions/workflows/ci.yml)
[![Latest release](https://img.shields.io/github/v/release/thedandano/callback)](https://github.com/thedandano/callback/releases)
[![License: MIT](https://img.shields.io/badge/license-MIT-green)](LICENSE.md)
[![Python 3.12+](https://img.shields.io/badge/python-3.12%2B-blue)](https://www.python.org/downloads/)
[![MCP compatible](https://img.shields.io/badge/MCP-compatible-brightgreen)](https://modelcontextprotocol.io/)

**Get past the resume filter so you talk to a human recruiter.**

Most job applications are rejected by software before a person ever reads them. callback
scores your resume against a specific job posting, shows you exactly which keywords you're
missing, rewrites your bullets to close the gap, and renders a finished PDF.

You drive it from the AI assistant you already use — Claude Code, Codex, or any other
[MCP](https://modelcontextprotocol.io/) client. There's no separate app to open.

**What makes it different:**

- **It won't lie for you.** Every rewritten bullet is built from evidence you gave it. It
  will not invent a skill, a job, or a metric — and it won't keyword-stuff.
- **The score is deterministic.** Plain Python, no model guessing. The same resume and the
  same posting always produce the same number, so you can tell whether an edit actually helped.
- **It tells you what it can't see.** The score predicts whether a recruiter's search finds
  you and whether the 10-second skim survives. It is not a prediction that you'll get an interview.

---

## What you'll need

- **Python 3.12 or newer**
- **[uv](https://docs.astral.sh/uv/getting-started/installation/)** on your `PATH`
- **An MCP client** — Claude Code and Codex have a one-command install below
- **Your resume** as a PDF, DOCX, or TXT file

---

## Quickstart

### 1. Install

In Claude Code:

```
/plugin marketplace add thedandano/callback
/plugin install callback@callback
```

Then restart your session (or run `/reload-plugins`). Other clients — Codex, Cursor, Claude
Desktop — see [Install](#install) below.

First launch is slow. `uvx` downloads the server and its dependencies, then the server
installs a headless Chromium browser in the background (used to fetch job postings and
render PDFs). Later launches are fast.

### 2. Set up your profile

callback can't tailor anything until it has your resume. In your assistant:

```
Set up callback for my job search
```

That runs the `setup-callback` skill, which registers your resume, builds your profile,
and captures what you're looking for. You only do this once.

Your profile is a set of **behavioral stories** — short write-ups of things you actually
did, in Situation / Behavior / Impact form. This is the evidence callback draws on when it
rewrites a bullet, and it's why the tool can tailor without fabricating. Onboarding will
prompt you for these, and you can add more later.

### 3. Tailor a resume

```
Tailor my resume for https://example.com/careers/some-job
```

You get back a scored gap report, a tailored PDF, and a JSON archive of the run. By default
these land in `~/.local/share/callback/applications/`.

> If your assistant runs in a sandbox that can't reach your home directory, tell it where to
> put the PDF and it will pass that through as the output directory.

---

## Everyday use

Once you're set up, these skills are the normal way in. Ask for them in plain English or
use the slash command.

| Skill | Use it to |
|---|---|
| `setup-callback` | Bootstrap everything in one pass — paths, resume, preferences. Start here. |
| `onboard-profile` | Register a resume, add accomplishments, or add a new story. |
| `tailor-resume` | Score and tailor for **one** job posting. |
| `scan-job-leads` | Find and dedupe job leads. Does not apply to anything. |
| `apply-to-job` | Score, tailor, stage, and record an application. |

Submitting an application always requires your explicit approval in the moment. callback
will not send anything on your behalf without it.

---

## How your resume is scored

Five dimensions, 100 points total. Each one stands in for a real gate your application has
to clear.

| Dimension | Max | What it measures |
|---|---|---|
| KeywordMatch | 55 | Required keywords (weighted 0.7) and preferred ones (0.3) — whether a recruiter's search finds you |
| ExperienceFit | 15 | Whether you meet the stated years of experience. Skipped and renormalized when the posting doesn't say. |
| ImpactEvidence | 10 | How many bullets carry a real, quantified result |
| ATSFormat | 10 | Standard section headings, so the parser doesn't mangle your resume |
| Readability | 10 | Absence of filler like "responsible for" and "worked on" |

Passing mark is 70.

**What this score cannot see:** work authorization, location, job-title match, how recent
your skills are, and degree or clearance filters. Those are among the most common reasons
applications get auto-rejected, and callback has no visibility into them. Treat the number
as "will I survive the search and the skim," not "will I get called."

Weights live in `ScoringConfig` in `callback/scorer.py`.

---

## Privacy

Worth being precise about, since this handles your resume.

**callback itself makes three kinds of outbound network calls:**

1. Fetching the job posting you asked for, from the URL you gave it.
2. A version check against the GitHub releases API.
3. LangSmith tracing — **off unless you turn it on**, and its traces are redacted to exclude
   resume text, posting text, story content, your edits, and file paths.

Scoring, parsing, and PDF rendering all run on your machine. callback makes no calls to any
AI model.

**However:** callback hands your resume sections to your MCP client so that *its* model can
write the tailored bullets. If that client is a cloud assistant, your resume content goes to
that provider under their terms, exactly as it would if you pasted it into the chat. That's
inherent to how the tool works, and you should know it.

Your profile, applications, and history are stored under `~/.local/share/callback/`.

---

## Install

### Claude Code (recommended)

```
/plugin marketplace add thedandano/callback
/plugin install callback@callback
```

Or from your shell, if the `claude` CLI is on your `PATH`:

```bash
callback setup-plugin --target claude       # --print-only to preview the commands first
```

### Codex

```
codex plugin marketplace add thedandano/callback
codex plugin add callback@callback
```

Or: `callback setup-plugin --target codex`.

### Any other MCP client

Add this to your client's MCP config. `uvx` fetches, builds, and runs the server straight
from GitHub — nothing to install separately.

```json
{
  "mcpServers": {
    "callback": {
      "command": "uvx",
      "args": [
        "--from",
        "git+https://github.com/thedandano/callback",
        "callback",
        "serve"
      ]
    }
  }
}
```

Restart the client afterward.

> Not on PyPI yet. Installing from the GitHub URL is the supported path for now.

### As a standalone CLI

Use this if you want the `callback` command itself — for scripting, or for a client without
plugin support. It is not needed for the plugin install above.

```bash
uv tool install git+https://github.com/thedandano/callback.git
callback install-browsers      # headless Chromium, for fetching postings and rendering PDFs
callback setup-mcp             # register the server with Claude and Codex
```

Restart your MCP client afterward. `setup-mcp` is deliberately noninteractive — it only
registers the server entry and preserves any `env` map already there. It does not ask for
API keys or set up tracing.

Run `callback config status` to confirm the registration and compare the Claude and Codex
entries. It's read-only and reports `same`, `different`, `missing`, or `unset`.

---

## Optional: tracing with LangSmith

callback runs fine without this. Turn it on if you want to inspect graph runs.

```bash
callback config langsmith                                  # guided setup
callback config langsmith --api-key lsv2-... --project Callback   # noninteractive

callback config status            # inspect; secrets redacted by default
callback config env list --show-secrets

callback config env set CALLBACK_TRACE_BACKEND langsmith --target all
callback config env unset LANGSMITH_API_KEY --target codex

callback trace-check --target codex --emit-test-trace      # verify it works
```

MCP clients launch `callback serve` as a subprocess, so these variables must live in the
client's MCP config `env` map — not your shell profile. Restart the client after any change.

<details>
<summary>Tracing details</summary>

Set `CALLBACK_TRACE_BACKEND=langsmith`, `LANGSMITH_TRACING=true`,
`LANGSMITH_ENDPOINT=https://api.smith.langchain.com`, `LANGSMITH_API_KEY=<key>`, and
optionally `LANGSMITH_PROJECT` (defaults to `Callback`).

Two layers are used: LangGraph `RunnableConfig` metadata for graph runs, and sanitized
decorator spans for MCP tool calls and graph nodes.

The server suppresses native LangChain/LangGraph auto-tracing around graph invocation,
because callback intentionally pauses its graphs to hand control back to the MCP client.
Without that suppression, LangSmith shows a graph run stuck as pending while it waits for
the next tool call. The sanitized `callback.*` spans are the supported surface.

Spans carry only safe fields: `session_id`, `tool_name`, `graph_name`, `node_name`,
`resume_label`, counts, and key names. Never resume text, posting text, story content,
submitted edits, file paths, or API keys.

</details>

---

## Maintenance

```bash
callback logs --follow          # default: ~/.local/state/callback/server.log
callback update                 # upgrade via uv tool upgrade
```

`callback logs` also takes `--project-logs` (reads `./.callback/server.log`) or
`--log-path <path>`.

To uninstall:

```bash
callback uninstall              # remove MCP server entries from Claude and Codex
uv tool uninstall callback      # remove the tool
```

Add `--purge` to the first step to also delete `~/.local/share/callback/` (your PDFs, JSON
archives, and session databases) and `~/.local/state/callback/` (logs). That is not reversible.

---

## Scheduling a recurring scan

Point a scheduler at the `scan-job-leads` skill.

Claude `/schedule`, weekday mornings:

```
/schedule "0 8 * * 1-5" Use the scan-job-leads skill. Read search preferences via get_search_preferences, scan configured sources within lead_recency_days, dedupe against the ledger, and return the standard scan-job-leads summary with recommended leads for apply-to-job.
```

Or plain cron:

```cron
0 8 * * 1-5  claude --print "Use the scan-job-leads skill." >> ~/job-scan.log 2>&1
```

Afterward, run `apply-to-job` on the leads you want. Submission still needs your explicit
approval.

---

## MCP tools

The skills above cover normal use. These are the underlying tools, for building your own
flow.

| Tool | Description |
|---|---|
| `load_jd` | Fetch a job posting from a URL, or accept raw text. Returns the posting as markdown plus extraction instructions. |
| `submit_keywords` | Accept the client-extracted job data (title, required and preferred keywords, seniority, years). Scores the resume and returns keyword gaps. |
| `submit_tailor` | Apply bullet edits, render the PDF, score the result, produce the report. |
| `get_wiki_pages` | Fetch pages from your behavioral-story profile by path. |
| `onboard_user` | Register a resume, skills file, and accomplishments doc. |
| `compile_profile` | Recompile your profile from all stored stories. |
| `create_story` | Save a new behavioral story for a skill. |
| `set_search_preferences` | Save your job-search preferences. |
| `get_search_preferences` | Read your job-search preferences. |
| `check_update` | Report the current version, the latest release tag, and whether an update is available. |

The client owns keyword extraction and tailoring judgment. callback owns state, validation,
scoring, rendering, and archival. The full handoff protocol is in
[CLAUDE.md](CLAUDE.md#agent-mcp-playbook).

---

## Development

```bash
git clone https://github.com/thedandano/callback.git
cd callback
uv sync
uv run playwright install chromium     # one-time

uv run pytest                          # tests
uv run pyright                         # type check
uv run ruff check                      # lint
uv run python -m callback.server       # run the server locally
```

For a development install that puts the CLI on your `PATH`:

```bash
make install && callback setup-mcp
```

`make install` embeds a build version derived from git. A clean checkout of `origin/main`
prints the package version; commits ahead of it get a suffix like `1.1.0-03-a1b2c3d`, and
uncommitted changes add `-dirty`.

Architecture, graph design, and change discipline are documented in
[CLAUDE.md](CLAUDE.md) and [BRIEF.md](BRIEF.md).

---

## License

[MIT](LICENSE.md).

---

If callback helped you get past a resume filter, **star the repo** — it's the easiest way to
help someone else find it. Bugs and ideas go in
[issues](https://github.com/thedandano/callback/issues). Forks and pull requests welcome.
