---
name: auto-job-apply
description: Runs the full unattended end-to-end job-search pipeline over many leads in one go — discovery, scoring, tailoring, staging, recording, and submit-on-approval. Use for a scheduled or autonomous run that sweeps configured sources (Gmail, Google Jobs, career pages) and processes the whole batch, updating automation memory and outcomes. Submission still requires explicit current-turn approval. Not for a single job (use tailor-resume), a single selected lead (use apply-to-job), or discovery-only scans (use scan-job-leads).
---

# Auto Job Apply

## North Star

Get the user a job by maximizing qualified interview chances: find and score leads inside the user's configured core domains and location preferences, avoid duplicate or spammy applications, and never submit an application until the user has reviewed and explicitly approved it in the current turn.

## Preferences

Call `get_search_preferences` at the start of every run. Apply the returned values throughout:

- **Location / work types** (`home_location`, `work_types`): hard curation gate. Keep only roles workable from the user's configured location. Do not curate roles outside that gate.
- **Target titles / seniority bands / seniority blockers** (`target_titles`, `seniority_bands`, `seniority_blockers`): use for ranking and blocking. Skip roles that match a configured blocker (e.g. staff/principal when the user targets mid-level).
- **Compensation** (`comp_annual_target`): priority signal, not a hard gate. Prefer roles at or above the target; still resolve and score otherwise strong roles below it — record the salary and note compensation risk / verify before applying. Record `Not listed` or `Ambiguous` when unclear.
- **Core / skip domains** (`core_domains`, `skip_domains`): keep roles primarily in core domains; skip skip-domain roles before scoring unless the user asks to stretch.
- **Target companies** (`target_companies`): always surface leads from these companies.
- **Referral companies** (`referral_companies`): read the list; surface referral leads for configured companies — do not special-case any company by name in this skill.
- **Scan sources** (`scan_sources`): scan the user's configured sources every run.
- **Lead recency** (`lead_recency_days`): constrain Gmail and web discovery to this window.

Also read the compiled profile once at the start of the run (via `get_wiki_pages` or the profile summary) for two gating facts that live on the candidate, not in preferences: total years of professional experience, and the core known-skills list. Use these for the two hard blockers below.

- **Years-of-experience hard blocker**: skip a lead before scoring if the posting states a required (not preferred) years-of-experience floor at or above ~1.75x the candidate's actual years from the profile. These are typically binary screener knockouts that no truthful resume edit can close. Do not apply this to soft/preferred framing ("5+ years preferred") or ranges that comfortably include the candidate's tenure.
- **Mandatory-missing-skill hard blocker**: skip a lead before scoring if the posting centers on a specific required tool, language, or domain that has zero presence anywhere in the candidate's profile and is core to the role rather than a minor nice-to-have (e.g. a required systems-language or a named datastore the role is built around). No truthful tailoring can add experience that doesn't exist, so don't spend a callback pass finding that out.
- **Domain-gate matching must see past employer branding**: a role's actual domain is what the JD is about, not what industry the employer is known for. A security/detection-engineering or contact-center/telephony-specialist role at an AI-forward company is still a `skip_domains` match if security/telephony is in the user's skip list — don't let "AI company" branding override an actual skip-domain hit.

## Required Files

Read all file paths from `.callback/config.json`:

- `applications_dir` — per-role run artifacts go here under `<YYYY-MM-DD>/<company-role-slug>/`. One folder per role per day; reuse the day's folder; do not create near-duplicate `...-run`/`...-rerun`/`...-subtask` variants.
- `record_csv` — canonical record CSV (one only); update in place.
- `ledger_db` — canonical ledger database; invoke via the `job-search-ledger` command.
- `edd_xlsx` — canonical Excel tracker (one only); update in place via `export-excel`.
- `archive_dir` — backups and dated exports only under sub-dirs (`csv_backups/`, `xlsx_exports/`, `sqlite_backups/`, `screenshots/`).

Automation memory and config live under the automation store managed by the scheduler — not at hardcoded paths. Never write scattered files to directory roots; keep canonical live data files in their configured locations.

## File Output Discipline

HARD rules — override any older path conventions:

- Exactly ONE canonical record CSV, ONE tracker, ONE ledger DB. Update in place. No timestamped or run-suffixed copies alongside them.
- Per-role artifacts go ONLY under `<applications_dir>/<YYYY-MM-DD>/<company-role-slug>/`. Slug: lowercase, hyphenated, `<company>-<role-keywords>`.
- Dated backups only when a bulk edit is genuinely risky — write to `<archive_dir>/csv_backups/` etc., never to the root.
- Screenshots under `<archive_dir>/screenshots/`, not the root.

## Run Title

For scheduled automation runs, compute the local date and 24-hour run-start hour in the user's configured timezone. Format: `Auto Job Apply - YYYY-MM-DD - HH PT`. Make this the first line of the final response as `Run title: Auto Job Apply - YYYY-MM-DD - HH PT`.

## Orchestrator Model

The parent agent is the run orchestrator. It owns run title, memory, source policy, dedupe, location/domain gates, scoring queue, CSV/job-ledger updates, automation memory updates, and the final user-facing summary.

Use subagents by default for independent work:

- **Gmail curator agent**: searches unread Gmail job alerts, recruiter threads, application confirmations, rejection/status emails, and forwarded job snippets only. Returns discovery leads only (no scoring, tailoring, sending, archiving, or labeling). After the parent fully handles every actionable item from a message, mark it read by removing `UNREAD`.
- **Source curator agents** (one per configured source in `scan_sources`): each agent scans its assigned source within `lead_recency_days` and returns only lead metadata. Do NOT load full email threads or JD text into the parent; each agent returns only the discovery table.
- **Source resolver agent**: takes one discovery lead at a time after the parent dedupes obvious repeats. Follows the URL chain to reach a full current JD source. Returns source-validation evidence only.
- **Callback role agents**: one role per agent after the parent validates the full current source and dedupes the queue. Each must run `load_jd -> submit_keywords -> get_wiki_pages` (when useful) `-> submit_tailor` with truthful edits only. Do not use `no_coverage=True` unless no truthful supported edits exist; label that result as no-coverage. For referral leads configured in `referral_companies`, surface real keyword/format gaps even when the tailored score is below 70 — the artifacts inform the referral ask.

If subagent tooling is unavailable, blocked, or inappropriate for a single-role run, the parent may perform the work directly but must state that exception in the final summary.

### Discovery Agent Return Contract

Each discovery agent must return a Markdown table with one row per lead:

| Company | Title | Source URL | Lead URL | Source date | Location/work type | Salary range | Level/seniority | Source status | Relevant info | Blockers/notes |
| ------- | ----- | ---------- | -------- | ----------- | ------------------ | ------------ | --------------- | ------------- | ------------- | -------------- |

`Source status`: one of `Full source visible`, `Source candidate - needs validation`, `Snippet only`, `Login/blocked`, `Closed`, `Duplicate candidate`, `Compensation risk`, or `Hard blocker`.

### Source Resolver Contract

Run a source-resolution pass before recording `Needs source - manual lookup` for any plausible lead. For each lead, try in order:

1. Open the lead URL or candidate URL.
2. Follow any `Apply`, `Apply on company site`, `View job`, or external ATS link.
3. Prefer employer/ATS outbound links from aggregators. If the aggregator exposes the complete JD and no employer source is reachable, it may serve as a direct third-party source.
4. Search the employer career site for exact `Company + Title`, `Company + job ID`, and `Company + Title + careers`.
5. Check likely ATS hosts: Greenhouse, Lever, Ashby, Workday, SmartRecruiters, Jobvite, iCIMS, Freshteam, Oracle, ADP, BambooHR, Rippling, and company careers pages.
6. Confirm the final source exposes the complete current JD, not a teaser or preview.

Resolver output must include `Source URL`, `Source status`, and `Resolution evidence`.

## Source Coverage

- **Gmail**: search only unread messages within `lead_recency_days`. Include `is:unread` or `label:unread`. Treat forwarded summaries, LinkedIn alert cards, Indeed digests as discovery leads only. After full reconciliation, remove `UNREAD` from processed messages.
- **Configured sources** (`scan_sources`): run one discovery subagent per source within `lead_recency_days`. Treat source cards and snippets as discovery only; open the full employer/ATS page before scoring.
- **FAANG careers**: search current official source/careers pages for all companies listed in `target_companies` that are FAANG-tier. Prefer the employer's official source over third-party mirrors.
- **FAANG level mapping**: use levels.fyi as a sanity check. Treat staff/principal bands as hard seniority blockers unless the user's `seniority_bands` explicitly includes them or the user asks for a stretch in the current turn.

## Source-Only Scoring Rule

- Score only from the full current job source: employer careers page, official ATS page, or directly opened third-party page with the complete JD.
- Do not run callback on email snippets, forwarded summaries, job-alert cards, or partial teaser text.
- If no full source URL or full source-page text is available, record `Needs source - manual lookup` and do not score.

## Workflow

1. Parent reads automation memory, computes run title, confirms run scope/time window, reads `get_search_preferences`.
2. Parent dispatches one discovery subagent per `scan_sources` entry (plus Gmail if configured) in parallel. Constrain each to `lead_recency_days`.
3. Discovery agents return the Discovery Agent Return Contract table only — no scoring, no tailoring.
4. Parent merges discovery tables into a shallow lead list. Deduplicates against the job search ledger first, then the record CSV. Dedupe order: exact URL → exact requisition/job ID → exact Title → Company plus similar Title.
5. Parent curates before scoring. Apply the location gate, then the domain gate (matching the JD's actual subject matter, not the employer's brand — see Preferences), then the years-of-experience and mandatory-missing-skill hard blockers from Preferences, then rank by configured `target_titles` and domain bias. Skip hard blockers: clearance, closed postings, heavy domain mismatch, obvious seniority mismatch (`seniority_blockers` or stated years), already-rejected same role/company. Treat compensation as a priority signal, not a gate.
6. Parent resolves full current sources for every plausible non-duplicate lead.
7. For leads from companies in `referral_companies`, parent surfaces them as referral leads with status `Referral lead - ask friend` before scoring.
8. Parent dispatches one callback role agent per validated queued role when more than one role is queued.
9. Each callback role agent scores and tailors using `load_jd -> submit_keywords -> get_wiki_pages` (when useful) `-> submit_tailor`. Truthful edits only. For referral leads, still surface real keyword and format gaps even when the tailored score is below 70.
10. Each callback role agent returns a standardized Markdown result row with source URL, company, title, salary, location, before score, after score, status recommendation, artifact links, strongest overlaps, missing keyword clusters, seniority/source risks, and whether actual edits were applied or this was no-coverage.
11. Parent reconciles callback results. For scores under 70, a mismatch explanation is required before moving on.
12. Tailored score under 70: record and do not apply. For referral leads, keep tailored artifacts and set status `Referral lead - ask friend`.
13. Tailored score 70+: stage as `Needs review - not applied`. Summarize why it is worth reviewing and any remaining mismatch risk. Preserve referral-first notes for referral leads.
14. Submit only after explicit user approval in the current turn.
15. Parent records every outcome and updates automation memory. For every real application, confirmation, or recruiter resume submission, record in the job search ledger and export the unemployment-compatible Excel workbook.

## Scoring And Application Rules

- Use the callback MCP workflow directly. Never create custom scoring scripts, alternate scoring logic, or non-callback scoring wrappers.
- If callback rendering needs unsandboxed Playwright/Chromium, request permission rather than falling back to guessed scores.
- Never use callback on email-only or snippet-only JD text.
- Capture salary range for each curated/scored/skipped lead. If no salary is listed, record `Not listed`. Annualize hourly/contract rates only when the source gives enough information. If the range starts below the user's `comp_annual_target`, mark as compensation risk and lower priority, but do not skip solely for that reason.
- Use levels.fyi as a sanity check when level mapping matters.

## Recording

Use the schema and status vocabulary in [record-schema.md](references/record-schema.md). `Recorded Date` is when the run recorded or acted on the row. `Email Date` is the source email timestamp. `Salary range` is required for new rows; use `Not listed` when unavailable.

Invoke the job search ledger via the `job-search-ledger` command (the command resolves the DB path from `.callback/config.json`). Record reportable contacts only when there was a real application, confirmation, or recruiter resume submission. Do not mark scored/skipped/needs-review leads as reportable.

After recording a reportable contact, run `export-excel` to update the canonical tracker in place at `edd_xlsx`.

## Final Summary

Use Markdown as the standardized output format. Short prose only for context before tables.

Report:

- Number of jobs found, curated, scored, applied
- Max/mean/min tailored scores
- Status emails recorded
- Referral leads found (including tailored artifacts and gaps even when score is below 70)
- Clear review queue
- For each scored role: salary range, final/before scores, status, one-line mismatch summary
- For each skipped role: salary range if available and the blocker/mismatch reason

### Final Markdown Template

```markdown
Run title: Auto Job Apply - YYYY-MM-DD - HH PT

## Stats

| Jobs found | Curated | Scored | Applied | Max score | Mean score | Min score | Status emails | Source-manual leads | Referral leads |
| ---------: | ------: | -----: | ------: | --------: | ---------: | --------: | ------------: | ------------------: | -------------: |
|          0 |       0 |      0 |       0 |       N/A |        N/A |       N/A |             0 |                   0 |              0 |

## Discovery Sources

| Source agent | Leads returned | Full sources | Needs manual source | Notes |
| ------------ | -------------: | -----------: | ------------------: | ----- |

## Scored Roles

| Company | Title | Source URL | Salary | Location/work type | Before | After | Status | Artifacts | Mismatch summary |
| ------- | ----- | ---------- | ------ | ------------------ | -----: | ----: | ------ | --------- | ---------------- |

## Review Queue

| Company | Title | Score | Action needed | Resume | Cover letter | Notes |
| ------- | ----- | ----: | ------------- | ------ | ------------ | ----- |

## Referral Leads

| Company | Title | Level mapping | Source URL | Score | Seniority risk | Keyword/format gaps | Referral action | Artifacts |
| ------- | ----- | ------------- | ---------- | ----: | -------------- | ------------------- | --------------- | --------- |

## Skipped Or Source-Limited

| Company | Title | Source/lead URL | Salary | Reason | Next action |
| ------- | ----- | --------------- | ------ | ------ | ----------- |
```
