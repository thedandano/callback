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
- **Compensation** (`comp_annual_target`): advisory priority, not a hard gate. Record salary when visible; omit `salary_range` when missing and render `Not listed` only in the summary; add a compensation-risk note when the range starts below the user's target.
- **Target titles / seniority bands / seniority blockers** (`target_titles`, `seniority_bands`, `seniority_blockers`): use for ranking and blocking. Skip roles that match a configured blocker.
- **Target companies** (`target_companies`): always check and surface leads from these companies.
- **Referral companies** (`referral_companies`): read the list; surface referral leads for those companies with status `Referral lead - ask friend`.
- **Scan sources** (`scan_sources`): scan only the user's configured sources.
- **Lead recency** (`lead_recency_days`): constrain discovery to postings within this window.

## Subagent Dispatch

Spawn one subagent per configured source in parallel. Each subagent returns **only lead metadata** (company, title, source URL, lead URL, location/work type, salary range, level, source status, notes). Do NOT load full email threads or full JD text into the parent agent. The parent merges and dedupes the returned tables.

Dispatch via the host's multi-agent workflow orchestration when available (Claude Code: the Workflow tool / `/workflows`). Discovery subagents run on the cheap tier — Claude Haiku (GPT-5.6 Luna on Codex); reserve higher tiers for the parent's merge/validation judgment.

Discovery subagent return contract — one row per lead:

| Company | Title | Source URL | Lead URL | Source date | Location/work type | Salary range | Level/seniority | Source status | Notes |
| ------- | ----- | ---------- | -------- | ----------- | ------------------ | ------------ | --------------- | ------------- | ----- |

`Source status`: one of `Full source visible`, `Source candidate - needs validation`, `Snippet only`, `Login/blocked`, `Closed`, `Duplicate candidate`, `Compensation risk`, or `Hard blocker`.

## Source Validation

Treat email cards, snippets, search cards, LinkedIn alerts, Indeed digests, and ZipRecruiter summaries as leads only. Before staging a role, resolve a full current source:

- employer careers page
- official ATS page
- directly opened third-party page exposing the complete JD

If no full source is found, record `Needs source - manual lookup` with attempted resolution steps through `record_status`.

## Paths

If `.callback/config.json` still has a `record_csv` or `ledger_db` key and that file exists, stop before any dedupe. Tell the user to run `callback ledger import --archives <applications_dir> --csv <record_csv> --contacts-db <ledger_db>` (`applications_dir` from `.callback/config.json`) once from a normal terminal (leave out the flag for a file they do not have). Remove those keys only when the import prints `skipped 0` (or the user explicitly discards every listed `skipped:` line); keep them if any unexpected skip remains so a partial import cannot make prior applications look new.

Dedupe every lead with `find_job(url=<URL>, company=<company>, title=<title>)`; skip a lead when `matched_by` is `key`, except when its latest status starts with `Needs source`: re-resolve the source, and if it now exposes a full JD, stage it as a new lead under the same URL. For a `company_title` or `key_title_mismatch` match (same URL, different stored title), or a similar title in `data.company_jobs`, compare the URLs and requisition IDs first and skip only when they confirm the same posting; a `company_jobs` entry with `ever_applied` true that you confirm is the same posting counts as a prior application; otherwise treat it as a new lead. For a confirmed-distinct `key_title_mismatch` (the new URL normalizes to the old job's key), record it with `record_status` with no `url` (company + title only) and put the URL in `note`, so it gets its own job. Record each classified outcome with `record_status`: `Needs source - manual lookup` for source-limited leads, the appropriate `Skipped ...` status for gated-out leads, and `Needs callback score - not applied` when a validated lead is staged (a scan never scores, so never record `Needs review - not applied` here). Pass `salary_range` only when known. Do not read or write a record CSV.

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
