# callback

[![CI](https://github.com/thedandano/callback/actions/workflows/ci.yml/badge.svg)](https://github.com/thedandano/callback/actions/workflows/ci.yml)
[![Latest release](https://img.shields.io/github/v/release/thedandano/callback)](https://github.com/thedandano/callback/releases)
[![License: MIT](https://img.shields.io/badge/license-MIT-green)](LICENSE.md)
[![Python 3.12+](https://img.shields.io/badge/python-3.12%2B-blue)](https://www.python.org/downloads/)
[![MCP compatible](https://img.shields.io/badge/MCP-compatible-brightgreen)](https://modelcontextprotocol.io/)

### Your resume is probably being rejected by software, not by people.

You send out forty applications and hear nothing. Most of the time that silence isn't a hiring manager passing on you. It's a filter that scanned your resume for the words the posting asked for, didn't find enough of them, and sorted you below the line where a recruiter stops reading.

callback closes that gap without lying on your behalf.

Give it a job posting. It scores your resume against that specific posting, tells you which keywords you're missing and what they're worth, rewrites your bullets using work you actually did, and hands back a finished PDF. It runs inside the AI assistant you already have open, so there's no new app to learn.

Roughly how a session goes:

```
You:      Tailor my resume for https://boards.example.com/senior-backend

callback: Score 58/100. Missing required: Kubernetes, Terraform, gRPC.
          Found matching evidence in 3 of your stories.
          Tailored 6 bullets. Rewrote 2 filler openers.
          Score 81/100. PDF ready.
```

**It will not make things up.** Every rewritten bullet is built from evidence you gave it during setup. It won't invent a skill you don't have, and it won't pad your resume with keywords you can't back up in an interview. A resume that clears the filter and then falls apart on the phone hasn't helped you.

**The score is real arithmetic, not a vibe.** Plain Python, no model in the loop. The same resume and the same posting always produce the same number, so when you change something you can tell whether it actually helped.

**It admits what it can't see.** The score predicts whether a recruiter's keyword search surfaces you and whether your resume survives a ten-second skim. It doesn't know about work authorization, location, or job-title match, and it will never promise you an interview.

---

## Install

You need [uv](https://docs.astral.sh/uv/getting-started/installation/) on your `PATH`, Python 3.12 or newer, and your resume as a PDF, DOCX, or TXT file. That's it. The server downloads itself.

### Claude Code

```
/plugin marketplace add thedandano/callback
/plugin install callback@callback
```

Restart your session, or run `/reload-plugins`.

### Codex

```
codex plugin marketplace add thedandano/callback
codex plugin add callback@callback
```

Restart your session afterward.

### Cursor, Claude Desktop, or any other MCP client

Paste this into the client's MCP config. `uvx` fetches, builds, and runs the server straight from GitHub, so there's nothing to install first.

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

Restart the client.

Give the first launch a minute. `uvx` downloads the server and its dependencies, then the server quietly installs a headless Chromium browser that it uses to read job postings and render PDFs. Every launch after that is quick.

<details>
<summary>Prefer the standalone CLI?</summary>

You don't need this for any of the installs above. Use it if you want the `callback` command in your own shell, for scripting or for a client without plugin support.

```bash
uv tool install git+https://github.com/thedandano/callback.git
callback install-browsers      # headless Chromium, for reading postings and rendering PDFs
callback setup-mcp             # register the server with Claude and Codex
```

Restart your MCP client afterward. `setup-mcp` is deliberately noninteractive. It registers the server entry, preserves any `env` map already there, and never asks for API keys or touches your tracing setup.

Run `callback config status` to confirm it worked. It's read-only, and it compares the Claude and Codex entries side by side, reporting each as `same`, `different`, `missing`, or `unset`.

</details>

> Not on PyPI yet. Installing from the GitHub URL is the supported path for now.

---

## First run

### Set up your profile

callback can't tailor anything until it knows about you. In your assistant, ask for it in plain English:

```
Set up callback for my job search
```

That runs the `setup-callback` skill, which registers your resume, builds your profile, and captures what you're looking for. You do this once.

Your profile is a set of behavioral stories: short write-ups of things you actually did, in Situation / Behavior / Impact form. That's the evidence callback pulls from when it rewrites a bullet, and it's the reason the tool can tailor without inventing anything. Setup will walk you through your first few, and you can add more whenever you think of them.

### Tailor your first resume

```
Tailor my resume for https://example.com/careers/some-job
```

You get a scored gap report, a tailored PDF, and a JSON archive of the whole run. By default these land in `~/.local/share/callback/applications/`.

If your assistant runs in a sandbox that can't reach your home directory, tell it where to put the PDF instead and it will pass that path through.

---

## Everyday use

Ask for these in plain English or use the slash command.

| Skill | Use it to |
|---|---|
| `setup-callback` | Set up everything in one pass: paths, resume, preferences. Start here. |
| `onboard-profile` | Register a resume, add accomplishments, or write a new story. |
| `tailor-resume` | Score and tailor for one job posting. |
| `scan-job-leads` | Find and dedupe job leads. Doesn't apply to anything. |
| `apply-to-job` | Score, tailor, stage, and record an application. |

Actually submitting an application always needs your approval in the moment. callback won't send anything on your behalf.

---

## How the score works

Five dimensions, 100 points. Each one stands in for a real gate your application has to clear.

| Dimension | Max | What it measures |
|---|---|---|
| KeywordMatch | 55 | Required keywords (weighted 0.7) and preferred ones (0.3). Whether a recruiter's search finds you at all. |
| ExperienceFit | 15 | Whether you meet the stated years of experience. Skipped and renormalized when the posting doesn't say. |
| ImpactEvidence | 10 | How many bullets carry a real, quantified result. |
| ATSFormat | 10 | Standard section headings, so the parser doesn't mangle your resume. |
| Readability | 10 | Absence of filler like "responsible for" and "worked on". |

Passing mark is 70. Weights live in `ScoringConfig` in `callback/scorer.py` if you want to argue with them.

The number is worth what it's worth. It can't see your work authorization, your location, whether your job title matches the req, how recent your skills are, or degree and clearance filters. Those account for a lot of automatic rejections and callback has no visibility into any of them. Read the score as "will I survive the search and the skim", not "will I get called".

---

## What happens to your resume

callback makes three kinds of outbound network calls. It fetches the job posting from the URL you give it. It checks the GitHub releases API for updates. And if you turn on LangSmith tracing, which is off by default, it sends traces that are redacted to exclude your resume text, posting text, story content, your edits, and your file paths.

Scoring, parsing, and PDF rendering all happen on your machine. callback never calls an AI model itself.

The part worth understanding: callback hands your resume sections to your MCP client so that client's model can write the tailored bullets. If you're using a cloud assistant, your resume content goes to that provider under their terms, the same as if you'd pasted it into the chat window. That's how the tool works, and you should know it before you point it at your resume.

Your profile, applications, and history live in `~/.local/share/callback/`.

---

## Optional: tracing with LangSmith

callback runs fine without this. Turn it on if you want to watch the graph execute.

```bash
callback config langsmith                                  # guided setup
callback config langsmith --api-key lsv2-... --project Callback   # noninteractive

callback config status            # inspect; secrets redacted by default
callback config env list --show-secrets

callback config env set CALLBACK_TRACE_BACKEND langsmith --target all
callback config env unset LANGSMITH_API_KEY --target codex

callback trace-check --target codex --emit-test-trace      # verify it works
```

MCP clients launch `callback serve` as a subprocess, so these variables have to live in the client's MCP config `env` map, not your shell profile. Restart the client after any change.

<details>
<summary>Tracing details</summary>

Set `CALLBACK_TRACE_BACKEND=langsmith`, `LANGSMITH_TRACING=true`,
`LANGSMITH_ENDPOINT=https://api.smith.langchain.com`, `LANGSMITH_API_KEY=<key>`, and
optionally `LANGSMITH_PROJECT`, which defaults to `Callback`.

Two layers are in play: LangGraph `RunnableConfig` metadata for graph runs, and sanitized
decorator spans for MCP tool calls and graph nodes.

The server suppresses native LangChain and LangGraph auto-tracing around graph invocation,
because callback deliberately pauses its graphs to hand control back to the MCP client.
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

`callback logs` also takes `--project-logs`, which reads `./.callback/server.log`, or
`--log-path <path>`.

To uninstall:

```bash
callback uninstall              # remove MCP server entries from Claude and Codex
uv tool uninstall callback      # remove the tool
```

Adding `--purge` to the first step also deletes `~/.local/share/callback/`, which holds your
PDFs, JSON archives, and session databases, along with `~/.local/state/callback/` for logs.
You can't undo that.

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

Afterward, run `apply-to-job` on the leads you want. Submitting still needs your approval.

---

## MCP tools

The skills above cover normal use. These are the tools underneath, if you want to build your
own flow.

| Tool | Description |
|---|---|
| `load_jd` | Fetch a job posting from a URL, or accept raw text. Returns the posting as markdown plus extraction instructions. |
| `submit_keywords` | Accept the client-extracted job data: title, required and preferred keywords, seniority, years. Scores the resume and returns keyword gaps. |
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
prints the package version. Commits ahead of it get a suffix like `1.1.0-03-a1b2c3d`, and
uncommitted changes add `-dirty`.

Architecture, graph design, and change discipline are documented in
[CLAUDE.md](CLAUDE.md) and [BRIEF.md](BRIEF.md).

---

## License

[MIT](LICENSE.md).

---

If callback got you past a filter, star the repo. That's the easiest way to help the next
person find it. Bugs and ideas go in [issues](https://github.com/thedandano/callback/issues).
Forks and pull requests welcome.
