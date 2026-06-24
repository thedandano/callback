# Profile Preferences Wiring + Skill De-PII — Design (Track A)

**Date:** 2026-06-23
**Status:** Approved — all decisions locked with user
**Branch:** `feat/plugin-cross-harness` (rebased on main, which has the search-preferences subsystem from #53)

## Problem

The job-search skills (`scan-job-leads`, `review-job-application`,
`auto-job-apply`, `setup-job-automation`) hardcode personal preferences (San
Diego, $150k, domain lists, FAANG/Netflix referral logic) and absolute file
paths (`/Users/dandano/...`, the CSV/ledger/EDD locations). Per review comments,
**no personalized logic or paths should live in the skills** — preferences
belong in the user profile (global), paths belong in per-project config, and both
are captured at onboarding.

## Goal

1. Move **all** personalized logic out of the skills into **profile preferences**.
2. Move **job-hunt file paths** into a **per-project `.callback/config.json`**.
3. A new **`init` skill** bootstraps a project folder (writes the config) and runs onboarding (profile + prefs) in one flow.
4. Skills read prefs (via `get_search_preferences`) and paths (from `.callback/config.json`) at runtime — hardcoding nothing.
5. `scan-job-leads` drives discovery through **subagents** (context hygiene).
6. Drop the bespoke `setup-job-automation` skill; document scheduling instead.
7. Skill polish + two north-star copy caveats.

## Non-Goals

- STAR (keep SBI; deferred).
- Ledger write-time validation / status split — that's **Track B**, in the `job-search-ledger` repo (separate spec).
- No public/private tiering.

## Global vs project (settled)

- **Global** (one per user, already in `~/.local/share/callback`, captured at onboarding): profile, stories, **preferences**, wiki, registered resumes, sessions, logs. Plus new **`input_paths`** (where the user's source files live).
- **Project** (`.callback/config.json` in the project dir): the job-hunt working data — `applications_dir`, `record_csv`, `ledger_db`, `edd_xlsx`, `archive_dir`.
- **Tool, not a path:** the EDD ledger is invoked by command (`job-search-ledger` on PATH, or `uvx --from git+…`). Optional; `init` may *offer* to install it. Never a hardcoded repo path.
- **Codex automation infra:** `~/.codex/automations/<id>/` (automation.toml, memory.md) stays as Codex infra — not part of `.callback/config.json`.

## Design

### 1. Extend `SearchPreferences` (callback/preferences.py)

```python
class ReferralCompany(BaseModel):
    name: str
    note: str | None = None          # e.g. "ask my friend on the platform team"

class SearchPreferences(BaseModel):
    # existing: schema_version, home_location, work_types, target_titles,
    #   seniority_bands, seniority_blockers, target_companies, core_domains,
    #   skip_domains, comp_currency, comp_annual_target, updated_at

    referral_companies: list[ReferralCompany] = Field(default_factory=list)  # replaces hardcoded Netflix "ask friend"
    scan_sources: list[str] = Field(default_factory=list)                     # e.g. ["gmail","google_jobs","company_careers"]
    lead_recency_days: int = 3
    input_paths: list[str] = Field(default_factory=list)                      # user's source-file locations (global)
```

`set/get_search_preferences` already validate the whole object — new fields ride along. Extend the existing prefs tests.

**Consumer contract:**
- `referral_companies` → host surfaces a "referral lead" (pause for outreach) for those companies; nothing special-cased in the skill.
- `scan_sources` / `lead_recency_days` → scan iterates configured sources within the window.
- `input_paths` → onboarding reads source files from these locations.

### 2. Per-project config (`.callback/config.json`)

Host-managed project file (the host has direct project file access; the MCP
server's cwd is not guaranteed to be the project root, so no MCP tool):

```json
{
  "applications_dir": "./applications",
  "record_csv": "./data/record.csv",
  "ledger_db": "./data/ledger.sqlite3",
  "edd_xlsx": "./data/tracker.xlsx",
  "archive_dir": "./archive"
}
```

No Python model is needed (YAGNI) — nothing in callback reads this file; the host
skills write & read it directly, and the host passes `applications_dir` to
`submit_tailor` as `output_dir`. The schema is documented in the `init` skill.
callback's own PDF output keeps using `output_dir` / `CALLBACK_APPS_DIR`.

### 3. `init` skill (new) — bootstrap a project + onboard

`init` is a **skill** (conversational; can write files AND run onboarding):
1. Scaffold the project: write `.callback/config.json` (prompt for paths or accept defaults) and create `data/`, `applications/`, `archive/`.
2. Run onboarding: ask for the resume + `input_paths`; call `onboard_user` → `compile_profile`.
3. Capture preferences: ask the preference questions; call `set_search_preferences(...)`.
4. Optionally offer to install the EDD ledger tool (`job-search-ledger`).

`onboard-profile` remains for re-onboarding / profile-only updates; `init` is the
first-run "prep this folder" entry point that composes config + onboarding + prefs.

### 4. De-PII the skills (`scan-job-leads`, `review-job-application`, `auto-job-apply`)

Replace every hardcoded value with a "read from preferences / project config" instruction:
- Location/comp/domains/companies/titles/seniority → read via `get_search_preferences`; apply the user's values as the gates + advisory comp note.
- Referral → read `referral_companies`; surface referral leads for those.
- Sources/recency → scan `scan_sources` within `lead_recency_days`.
- Paths → read from `.callback/config.json`; ledger via the `job-search-ledger` command.
- Remove stale `pi-apply` / `pi_apply_applications/` references.

### 5. `scan-job-leads` subagents

Fan out one subagent per configured source (parallel); each returns only lead
metadata (company/title/URL). **Do not load full email threads into the parent
context.** Parent merges + dedupes.

### 6. Drop `setup-job-automation`

Delete the skill + its command. Add a README **"Scheduling a recurring scan"**
note: point your scheduler at the `scan-job-leads` skill — one example for Claude
`/schedule` and one for `cron`.

### 7. Polish + north-star caveats (all remaining skills)

- Rewrite `description`s in third person, broader trigger coverage.
- Drop the non-standard `version:` frontmatter key.
- Fix stale `pi-apply` naming.
- **North-star #6:** where the skills cite "covered skills," note that *covered = mentioned in a bullet, not necessarily demonstrated* (don't over-claim coverage).
- **North-star #7:** the sub-70 referral path (`auto-job-apply`) must still **surface the real keyword/format gaps** alongside the referral framing.

## Milestones

- **A1** — extend `SearchPreferences` (`ReferralCompany` + referral_companies, scan_sources, lead_recency_days, input_paths) + tests. *(code, TDD — only Python milestone)*
- **A2** — `init` skill (documents the `.callback/config.json` schema; scaffolds config + dirs; runs onboarding; captures prefs; offers ledger install). *(skill)*
- **A3** — de-PII `scan` / `review` / `auto` to read prefs + config; add scan subagents; drop `setup-job-automation` (+ its command, + README scheduling note); polish + north-star caveats. *(skills + docs)*
