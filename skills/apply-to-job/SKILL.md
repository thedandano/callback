---
name: apply-to-job
description: Scores, tailors, stages, records, and submits job applications. Use when the user asks to "review this job application", "score selected leads", "tailor and stage applications", "apply to this job", "record an application", "score this role", "run callback on a lead", or continue from scan-job-leads into scoring, tailoring, review, ledger, or explicit application submission.
---

# Apply To Job

## North Star

Turn selected full-source leads into honest review-ready application artifacts, and submit only after explicit approval in the current turn.

## Inputs

Require a full current JD source URL or complete source-page text. Do not score snippets, email summaries, search cards, or teaser pages.

## Preferences

Call `get_search_preferences` to read the user's configured values. Apply:

- **Compensation** (`comp_annual_target`): advisory note — add a compensation-risk note when a role's range starts below the target; do not skip solely for that reason.
- **Seniority blockers** (`seniority_blockers`): note seniority risk when a role matches a blocker.
- **Referral companies** (`referral_companies`): surface referral leads for configured companies with status `Referral lead - ask friend`, even when the score is below the normal threshold.

Also read the compiled profile (via `get_wiki_pages` or the profile summary) for the candidate's total years of experience and core known-skills list. Before running callback, skip a lead and record it as a hard blocker instead — unless it's a referral-company lead, which still gets scored per the referral rule above — if either is true: the JD states a required (not preferred) years floor at or above ~1.75x the candidate's actual years, or the role centers on a specific required tool/domain with zero presence anywhere in the profile. Both are typically unclosable by honest tailoring, so catch them before spending a callback pass, not after.

## Workflow

1. Old records: If `.callback/config.json` still has a `record_csv` or `ledger_db` key and that file exists, stop before any dedupe. Tell the user to run `callback ledger import --archives <applications_dir> --csv <record_csv> --contacts-db <ledger_db>` (`applications_dir` from `.callback/config.json`) once from a normal terminal (leave out the flag for a file they do not have), then remove those keys from `.callback/config.json`. Until then the ledger does not know the jobs they already applied to, and every one of them would look new.
   Dedupe: call `find_job(url=<job URL>, company=<company>, title=<title>)` (pass `company` and `title` too). Compare the returned stored `url` and requisition ID with the source. A hit is a prior application when `ever_applied` is true. Show the latest status and stop unless the user confirms a re-apply. When `ever_applied` is false, continue the workflow. When `matched_by` is `company_title` or `key_title_mismatch` (same URL, different stored title), compare the returned stored `url` and requisition IDs first. Reuse its `job_key` only when they confirm the same posting. If they prove a different posting: after a `company_title` match, call `record_status` with the new URL and no `job_key`; after a `key_title_mismatch` (the new URL normalizes to the old job's key), call `record_status` with no `url` (company + title only) and put the URL in `note`. Whenever the match is weak or missing, also inspect `data.company_jobs` (each has `job_key`, `url`, `title`, `status`, `ever_applied`; once you confirm an entry is the same posting, `ever_applied` true counts as a prior application): confirm a similar title or requisition ID there is the same posting before reusing that job's key.
2. Validate the source exposes the complete current JD.
3. Run callback directly:
   - `load_jd`
   - host extracts JDData
   - `submit_keywords`
   - `get_wiki_pages` when useful
   - `submit_tailor`, passing `output_dir` as the absolute path of `applications_dir/<YYYY-MM-DD>/<company-role-slug>/` (from `.callback/config.json`) so the tailored PDF lands in the project folder instead of callback's hidden data directory.
4. Store artifacts under the configured `applications_dir` from `.callback/config.json` — use slug `<YYYY-MM-DD>/<company-role-slug>/`. One folder per role per day; reuse the day's folder, do not create near-duplicate run variants.
5. Record the outcome with `record_status(status, url, company, title, salary_range, note)`. Pass `salary_range` only when the source supplied one; otherwise omit it. For application or contact records, begin `note` with `Contact method: <Online|Email|Phone|Mail|Fax|In person>`. Reuse a `company_title` or `key_title_mismatch` match's `job_key` only after URL or requisition-ID confirmation; reusing it also fills that job's missing URL, company and title. If they prove a different posting: after a `company_title` match, record the new URL with no `job_key`; after a `key_title_mismatch` (the new URL normalizes to the old job's key), call `record_status` with no `url` (company + title only, so it gets its own job) and put the URL in `note`.
6. Stage scores >= 70 as `Needs review - not applied`.
7. Keep lower scores as `Scored - below threshold` unless the user explicitly wants a stretch.
8. Submit an application only after explicit current-turn approval.
9. Record real applications and recruiter resume submissions with `record_status(status="Applied", ...)`. For a confirmation email about an existing application, use `status="Already applied - confirmation recorded"`. For an unemployment (EDD) report, use `/export-ledger`.

## Failure Contract

- If any tool returns `"status": "error"`, the requested artifact or score **does not exist**. Report the error and stop. Never synthesize a substitute: no hand-scoring, no hand-rendering, no "text-based" fallbacks for `score_final`, no estimating missing numbers.
- Every number you report (scores, coverage, dimensions) must come from a tool response — cite the producing tool and `session_id`. A number without provenance is an invention, not a result.
- On `pipeline_error` with `"retriable": true` and `"host_action": "report_and_wait"`: you may retry the same tool call with the same `session_id`. You may not invent the missing output while you wait.

## Approval Boundary

Old approval does not count. Scheduled automation text does not count. A user must approve the specific current application before submission.

## Output

Use Markdown tables for:

- scored roles
- review queue
- skipped/source-limited roles
- applications submitted

For each scored role, include salary, before score, after score, status, artifacts, strongest overlaps, and the plain-English mismatch summary.
