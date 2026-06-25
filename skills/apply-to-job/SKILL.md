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

## Workflow

1. Dedupe against the job search ledger first, then the CSV record.
2. Validate the source exposes the complete current JD.
3. Run callback directly:
   - `load_jd`
   - host extracts JDData
   - `submit_keywords`
   - `get_wiki_pages` when useful
   - `submit_tailor`
4. Store artifacts under the configured `applications_dir` from `.callback/config.json` — use slug `<YYYY-MM-DD>/<company-role-slug>/`. One folder per role per day; reuse the day's folder, do not create near-duplicate run variants.
5. Record status in the CSV at `record_csv` from `.callback/config.json`.
6. Stage scores >= 70 as `Needs review - not applied`.
7. Keep lower scores as `Scored - below threshold` unless the user explicitly wants a stretch.
8. Submit an application only after explicit current-turn approval.
9. For real applications, confirmations, or recruiter resume submissions, update the job search ledger via the `job-search-ledger` command and export the unemployment-compatible workbook to the path at `edd_xlsx`.

## Approval Boundary

Old approval does not count. Scheduled automation text does not count. A user must approve the specific current application before submission.

## Output

Use Markdown tables for:

- scored roles
- review queue
- skipped/source-limited roles
- applications submitted

For each scored role, include salary, before score, after score, status, artifacts, strongest overlaps, and the plain-English mismatch summary.
