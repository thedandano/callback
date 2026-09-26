---
name: setup-callback
description: This skill should be used when the user asks to "set up callback in this project", "start a job hunt here", "initialize callback", "bootstrap my job search", "set up my job search project", "init callback", or "configure callback for this project". Use it to scaffold project paths, onboard a resume, capture search preferences, and optionally set up California EDD/ledger tracking — in one pass.
---

# Setup Callback

## North Star

Get the user past the ATS gate by preparing an honest candidate profile and project structure before any job search or tailoring begins.

## Flow

### 1. Scaffold project

Write `.callback/config.json` in the project root. Prompt for each path or accept defaults:

```json
{
  "applications_dir": "./applications",
  "record_csv": "./data/record.csv",
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

Ask if the user wants unemployment reporting tracking. This is specific to
California's **EDD** (Employment Development Department) job-search
contact-reporting requirement for **Unemployment Insurance** claimants — it
does not apply to Disability Insurance (which covers wage loss while unable to
work and carries no job-search requirement), and it does not apply outside
California. Most users should skip it. Ask plainly: "Are you filing a
California unemployment insurance claim and need to log job-search contacts
for EDD?"

If yes:
1. Tell them to install the `job-search-ledger` tool so the command stays on
   `PATH`: `uv tool install git+<repo-url>` (do not hardcode a repo path — point
   the user to the project docs for the actual URL).
2. Add `ledger_db` and `edd_xlsx` to `.callback/config.json` alongside the keys
   from step 1, e.g. `"ledger_db": "./data/ledger.sqlite3"` and `"edd_xlsx":
   "./data/tracker.xlsx"`.

If no, or the user is outside California, skip this step entirely — every other
callback feature works fully without it.

## Rules

- No hardcoded personal values, absolute paths, or company/location defaults.
- Paths live in `.callback/config.json`; preferences live in the profile via `set_search_preferences`.
- Re-running init updates config and prefs in place.
- Truthful evidence only — never fabricate or keyword-stuff.
