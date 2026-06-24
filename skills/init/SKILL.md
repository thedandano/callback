---
name: init
description: This skill should be used when the user asks to "set up callback in this project", "start a job hunt here", "initialize callback", "bootstrap my job search", "set up my job search project", "init callback", or "configure callback for this project". Use it to scaffold project paths, onboard a resume, capture search preferences, and optionally set up ledger tracking — in one pass.
---

# Init

## North Star

Get the user past the ATS gate by preparing an honest candidate profile and project structure before any job search or tailoring begins.

## Flow

### 1. Scaffold project

Write `.callback/config.json` in the project root. Prompt for each path or accept defaults:

```json
{
  "applications_dir": "./applications",
  "record_csv": "./data/record.csv",
  "ledger_db": "./data/ledger.sqlite3",
  "edd_xlsx": "./data/tracker.xlsx",
  "archive_dir": "./archive"
}
```

Create the directories: `data/`, `applications/`, `archive/`.

Re-running this step updates the config in place — no duplicates.

### 2. Onboard

Ask for:
- `resume_path` — PDF, DOCX, or TXT.
- `input_paths` — optional list of additional source files (skills docs, accomplishments).

Then:
1. Call `onboard_user(resume_path=..., input_paths=[...])`.
2. On success (`next_action: compile_profile`), call `compile_profile()`.
3. Report: registered label, detected sections, warnings, skill coverage gaps, next action.

Never fabricate experience, skills, dates, metrics, or tools.

### 3. Capture preferences

Ask these questions (skip any the user already answered):

- **Location:** home city/state; remote preference.
- **Work types:** e.g. `["full_time", "contract"]`.
- **Comp target:** annual total comp (USD or omit).
- **Target titles:** list of preferred job titles.
- **Seniority bands + blockers:** bands you want (e.g. `["senior", "staff"]`); titles/levels to exclude.
- **Target companies:** companies of interest.
- **Core domains / skip domains:** domains to prioritize vs. skip.
- **Referral companies:** companies where you have a contact (`name` + optional `note`).
- **Scan sources:** where to look for leads (e.g. `["gmail", "linkedin", "company_careers"]`).
- **Lead recency (days):** how many days back to scan (default: 3).

Then call `set_search_preferences(...)` with all answers. Note: this fully replaces stored prefs, so collect everything before calling.

### 4. Ledger install (optional)

Ask if the user wants EDD/unemployment tracking. If yes, tell them to install the `job-search-ledger` tool — e.g.:

```
uvx --from git+<repo-url> job-search-ledger
```

or add it to PATH if already installed. Do not hardcode a repo path; point the user to the project docs. Skip this step if not wanted.

## Rules

- No hardcoded personal values, absolute paths, or company/location defaults.
- Paths live in `.callback/config.json`; preferences live in the profile via `set_search_preferences`.
- Re-running init updates config and prefs in place.
- Truthful evidence only — never fabricate or keyword-stuff.
