# pi-apply

[![CI](https://github.com/thedandano/pi-apply/actions/workflows/ci.yml/badge.svg)](https://github.com/thedandano/pi-apply/actions/workflows/ci.yml)
[![Python 3.12+](https://img.shields.io/badge/python-3.12%2B-blue)](https://www.python.org/downloads/)

**Get past the ATS gate so you talk to a human recruiter.**

pi-apply is a [Model Context Protocol](https://modelcontextprotocol.io/) (MCP) server for job applications. It fetches job descriptions, scores your resume against ATS keyword requirements, tailors resume bullets using your wiki of behavioral stories, and renders a PDF — all orchestrated by your MCP host (Claude, Codex, etc.).

---

## Install

> **Requires** `uv` — [install uv](https://docs.astral.sh/uv/getting-started/installation/)

```bash
# 1. Install pi-apply from GitHub
uv tool install git+https://github.com/thedandano/pi-apply.git

# 2. Install Playwright Chromium (needed for URL-based JD fetching)
pi-apply install-browsers

# 3. Register the MCP server with Claude and Codex
pi-apply setup-mcp
```

After `setup-mcp`, restart your MCP host (Claude Desktop, etc.) to pick up the new server.

---

## Update

```bash
pi-apply update
```

Upgrades to the latest release via `uv tool upgrade`.

---

## Uninstall

```bash
# Step 1: remove MCP server entries from Claude and Codex configs
pi-apply uninstall

# Step 2: remove the tool itself
uv tool uninstall pi-apply
```

Add `--purge` to step 1 to also delete application data and state directories:

```bash
pi-apply uninstall --purge
```

`--purge` deletes `~/.local/share/pi-apply/` (application PDFs and JSON archives) and
`~/.local/state/pi-apply/` (LangGraph SQLite checkpointer databases and logs).

---

## How to use (MCP tools)

Once the server is running, your MCP host can call these tools:

| Tool | Description |
|---|---|
| `load_jd` | Fetch a job description from a URL or accept raw text. Returns JD markdown and extraction instructions. |
| `submit_keywords` | Submit host-extracted `JDData` (title, required/preferred keywords, seniority, years). Scores your resume and returns keyword gaps. |
| `submit_tailor` | Apply bullet edits to your resume SectionMap and finalize — renders PDF, scores final result, produces report. |
| `get_wiki_pages` | Fetch pages from your behavioral-story wiki by path. |
| `onboard_user` | Register a new resume, skills file, and accomplishments doc. |
| `compile_profile` | Recompile your profile from all stored stories. |
| `create_story` | Persist a new behavioral story (SBI format) for a skill. |
| `check_update` | Return current version, latest GitHub release tag, and `update_available` flag. |

### Agent MCP Playbook

When a user asks to use pi-apply for a job, the MCP host should follow the workflow metadata returned by each tool:

1. Call `load_jd` with `jd_url` or `jd_raw_text`.
2. Extract compact JDData from `data.jd_text` using `data.extraction_protocol`.
3. Call `submit_keywords` with the same `session_id` and the compact `jd_json` string.
4. If `workflow.next_tool` is `get_wiki_pages`, use `data.wiki_index` to fetch relevant evidence pages, then call `submit_tailor`.
5. If `workflow.next_tool` is `submit_tailor`, create honest edits from `data.sections`, `data.score_gap`, wiki evidence, and `data.tailor_instructions`.
6. If `workflow.next_tool` is `onboard_user` or `create_story`, collect the missing profile evidence, compile the profile, then restart the job flow with `load_jd`.
7. After `submit_tailor`, return `data.pdf_path`, `data.archive_path`, `data.report`, and `data.outcome` to the user.

The host owns keyword extraction and tailoring judgment. pi-apply owns state, validation, rendering, scoring, and archival.

### Scoring dimensions

| Dimension | Max pts | Signal |
|---|---|---|
| KeywordMatch | 45 | Required (×0.7) + preferred (×0.3) keywords |
| ExperienceFit | 25 | Years met + seniority match |
| ImpactEvidence | 10 | Quantified metric bullets |
| ATSFormat | 10 | Standard section headers present |
| Readability | 10 | Absence of filler phrases |

---

## Development

```bash
# Clone and install with dev dependencies
git clone https://github.com/thedandano/pi-apply.git
cd pi-apply
uv sync

# One-time browser setup
uv run playwright install chromium

# Run tests
uv run pytest

# Type check
uv run pyright

# Run the MCP server locally
uv run python -m pi_apply.server
```
