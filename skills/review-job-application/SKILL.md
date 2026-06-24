---
name: review-job-application
description: This skill should be used when the user asks to "review this job application", "score selected leads", "tailor and stage applications", "apply to this job", "record an application", or continue from scan-job-leads into scoring, tailoring, review, ledger, or explicit application submission.
version: 0.1.0
---

# Review Job Application

## North Star

Turn selected full-source leads into honest review-ready application artifacts, and submit only after explicit approval in the current turn.

## Inputs

Require a full current JD source URL or complete source-page text. Do not score snippets, email summaries, search cards, or teaser pages.

## Workflow

1. Dedupe against the job search ledger first, then the CSV record.
2. Validate the source exposes the complete current JD.
3. Run callback directly:
   - `load_jd`
   - host extracts JDData
   - `submit_keywords`
   - `get_wiki_pages` when useful
   - `submit_tailor`
4. Store artifacts under the existing job-hunt artifact convention:
   `~/REDACTED/pi_apply_applications/<run-slug>/`
5. Record status in `Codex_Job_application_record.csv`.
6. Stage scores >= 70 as `Needs review - not applied`.
7. Keep lower scores as `Scored - below threshold` unless the user explicitly wants a stretch.
8. Submit an application only after explicit current-turn approval.
9. For real applications, confirmations, or recruiter resume submissions, update the durable job-search ledger and export the unemployment-compatible workbook.

## Approval Boundary

Old approval does not count. Scheduled automation text does not count. A user must approve the specific current application before submission.

## Output

Use Markdown tables for:

- scored roles
- review queue
- skipped/source-limited roles
- applications submitted

For each scored role, include salary, before score, after score, status, artifacts, strongest overlaps, and the plain-English mismatch summary.
