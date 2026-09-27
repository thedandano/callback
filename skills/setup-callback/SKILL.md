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
1. Ask whether they already have the personal `job-search-ledger` command
   installed. Do not invent an install URL or repository. If they do not, skip
   ledger setup; callback remains fully functional without it.
2. Add `ledger_db` and `edd_xlsx` to `.callback/config.json` alongside the keys
   from step 1, e.g. `"ledger_db": "./data/ledger.sqlite3"` and `"edd_xlsx":
   "./data/tracker.xlsx"`.

If no, the user is outside California, or the command is not installed, remove
any existing `ledger_db` and `edd_xlsx` keys from `.callback/config.json`. Every
other callback feature works fully without them.

## Rules

- No hardcoded personal values, absolute paths, or company/location defaults.
- Paths live in `.callback/config.json`; preferences live in the profile via `set_search_preferences`.
- Re-running init updates config and prefs in place.
- Truthful evidence only — never fabricate or keyword-stuff.
