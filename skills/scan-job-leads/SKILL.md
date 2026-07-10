---
name: scan-job-leads
description: Discovers, validates, dedupes, and stages job leads without applying. Use when the user asks to "scan job leads", "find job leads", "check Gmail job alerts", "run the job lead scan", "search FAANG careers", "search recent software jobs", "look for open roles", "check for new postings", or run any job-search discovery workflow. Does not tailor resumes or submit applications.
---

# Scan Job Leads

## North Star

Find plausible leads that match the user's configured preferences while avoiding duplicates, snippets, stale postings, and spammy application behavior.

## Scope

Discovery only. This skill may find, validate, dedupe, and stage leads. It must not submit applications, tailor resumes, reply to recruiters, or mark a role as applied.

## Preferences

Call `get_search_preferences` at the start of every run. Apply the returned values as the gates:

- **Location / work types** (`home_location`, `work_types`): hard curation gate. Keep only roles workable from the user's configured location or work types. Skip remote roles tied to another metro/state/country.
- **Core / skip domains** (`core_domains`, `skip_domains`): domain gate. Prefer core-domain roles; skip skip-domain roles unless the user asks to stretch. Match the JD's actual subject matter, not the employer's brand — a security/detection-engineering or telephony-specialist role at an AI-forward company is still a `skip_domains` match if that domain is on the skip list.
- **Compensation** (`comp_annual_target`): advisory priority, not a hard gate. Record salary when visible; use `Not listed` when missing; add a compensation-risk note when the range starts below the user's target.
- **Target titles / seniority bands / seniority blockers** (`target_titles`, `seniority_bands`, `seniority_blockers`): use for ranking and blocking. Skip roles that match a configured blocker.
- **Target companies** (`target_companies`): always check and surface leads from these companies.
- **Referral companies** (`referral_companies`): read the list; surface referral leads for those companies with status `Referral lead - ask friend`.
- **Scan sources** (`scan_sources`): scan only the user's configured sources.
- **Lead recency** (`lead_recency_days`): constrain discovery to postings within this window.

## Subagent Dispatch

Spawn one subagent per configured source in parallel. Each subagent returns **only lead metadata** (company, title, source URL, lead URL, location/work type, salary range, level, source status, notes). Do NOT load full email threads or full JD text into the parent agent. The parent merges and dedupes the returned tables.

Discovery subagent return contract — one row per lead:

| Company | Title | Source URL | Lead URL | Source date | Location/work type | Salary range | Level/seniority | Source status | Notes |
| ------- | ----- | ---------- | -------- | ----------- | ------------------ | ------------ | --------------- | ------------- | ----- |

`Source status`: one of `Full source visible`, `Source candidate - needs validation`, `Snippet only`, `Login/blocked`, `Closed`, `Duplicate candidate`, `Compensation risk`, or `Hard blocker`.

## Source Validation

Treat email cards, snippets, search cards, LinkedIn alerts, Indeed digests, and ZipRecruiter summaries as leads only. Before staging a role, resolve a full current source:

- employer careers page
- official ATS page
- directly opened third-party page exposing the complete JD

If no full source is found, record `Needs source - manual lookup` with attempted resolution steps.

## Paths

Read file paths from `.callback/config.json` (`record_csv`, `ledger_db`). Invoke the ledger via the `job-search-ledger` command — do not hardcode a repo or database path.

## Output

Return a Markdown table:

| Company | Title | Source URL | Lead URL | Salary | Location | Source status | Recommendation | Notes |
| --- | --- | --- | --- | --- | --- | --- | --- | --- |

End with:

- jobs found
- curated leads
- full sources
- source-limited leads
- duplicates/skips
- recommended next action: usually run `apply-to-job` on selected full-source leads
