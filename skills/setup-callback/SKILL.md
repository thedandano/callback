---
name: setup-callback
description: This skill should be used when the user asks to "set up callback in this project", "start a job hunt here", "initialize callback", "bootstrap my job search", "set up my job search project", "init callback", or "configure callback for this project". Use it to scaffold project paths, onboard a resume, capture search preferences, and optionally set up California EDD/ledger tracking — in one pass.
---

# Setup Callback

## North Star

Get the user past the ATS gate by preparing an honest candidate profile and project structure before any job search or tailoring begins.

## Flow

### 1. Scaffold project

On an existing project, load `.callback/config.json` first.
Keep its `record_csv`, `ledger_db`, and `edd_xlsx` keys when present; remove them only after the
later import succeeds with `skipped 0`. Write the config in the project root. Prompt for each path or accept
defaults:

```json
{
  "applications_dir": "./applications",
  "archive_dir": "./archive"
}
```

Create the directories: `applications/`, `archive/`.
Add `.callback/` to the project's `.gitignore` (append it; never replace the
existing ignore rules) so automation memory and job-search details stay local.

Re-running this step updates the config in place — no duplicates.

### 2. Onboard

Ask for:
- `resume_path` — PDF, DOCX, or TXT.
- `accomplishments_path` — optional plain-text accomplishments file.

Then:
1. Call `onboard_user(resume_path=..., accomplishments_path=...)`.
2. On success (`next_action: compile_profile`), call `compile_profile(session_id=...)` with its returned session ID.
3. If `accomplishments_path` is supplied, follow `onboard-profile`'s Scan → Plan
   → Confirm → Compile workflow to create the approved stories before reporting
   setup complete.
4. Report: registered label, detected sections, warnings, skill coverage gaps, next action.

Never fabricate experience, skills, dates, metrics, or tools.

### 3. Capture preferences

Ask these questions (skip any the user already answered):

- **Location:** home city/state; remote preference.
- **Work types:** one or more of `onsite_local`, `hybrid_local`, or `remote`.
- **Comp target:** annual total comp (USD or omit).
- **Target titles:** list of preferred job titles.
- **Seniority bands + blockers:** bands you want (e.g. `["senior", "staff"]`); titles/levels to exclude.
- **Target companies:** companies of interest.
- **Core domains / skip domains:** domains to prioritize vs. skip.
- **Referral companies:** companies where you have a contact (`name` + optional `note`).
- **Scan sources:** structured sources, e.g. `[{"name": "Gmail alerts", "kind": "email", "instructions": "Search job-alert emails"}]`. `kind` is one of `email`, `web_search`, `careers_page`, or `job_board`.
- **Lead recency (days):** how many days back to scan (default: 3).
- **Sponsorship and work authorization:** whether sponsorship is needed, and the
  user's current authorization status.
- **Actual years of experience:** the truthful total; use `yoe_gap_multiplier`
  `1.75` unless the user specifies another value.

Then call `set_search_preferences(...)` with all answers. Note: this fully replaces stored prefs, so collect everything before calling.

### 4. Job history (optional)

Job history lives in callback's global ledger. Build one `callback ledger import` command from only the legacy sources that actually exist: add `--archives <folder>` for run archives, `--csv <path>` for an old record CSV, and `--contacts-db <path>` for an old `job_search_ledger.sqlite3`. Do not pass an absent source as a flag. After the import exits successfully with `skipped 0`, remove `record_csv`, `ledger_db`, and `edd_xlsx` from `.callback/config.json`. Keep those keys when the CLI lists any `skipped:` lines (malformed archive, bad date, ambiguous company/title, and so on) until the user fixes or explicitly discards every skip — a non-zero skip list means migration is incomplete even though the command exited 0. Keep them on a failed import too so the command can be retried. For an unemployment (EDD) report, use `/export-ledger`.

## Rules

- No hardcoded personal values, absolute paths, or company/location defaults.
- Paths live in `.callback/config.json`; preferences live in the profile via `set_search_preferences`.
- Re-running init updates config and prefs in place.
- Truthful evidence only — never fabricate or keyword-stuff.
