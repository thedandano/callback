---
name: setup-job-automation
description: This skill should be used when the user asks to "set up job automation", "create a job scan automation", "update auto-job-apply", "schedule job lead scanning", "configure recurring job search", or replace the old auto-job-apply workflow with callback plugin automation.
version: 0.1.0
---

# Setup Job Automation

## North Star

Set up recurring job-search automation that maximizes qualified interview chances without spammy or unapproved applications.

## Default Policy

Scheduled runs default to `scan-job-leads`, not the full apply loop. Automation may discover, validate, dedupe, and stage leads. Application submission requires explicit current-turn approval through `review-job-application`.

## Automation Defaults

Preserve existing values unless the user asks to change them:

- automation id: keep `auto-job-apply` as the migration alias
- name: `Auto Job Apply` or `Job Lead Scan`
- status: `ACTIVE`
- cwd: `/Users/dandano/Documents/Claude/Projects/Job hunt`
- model and reasoning effort: preserve current automation values
- schedule: preserve current RRULE

## Setup Workflow

1. Inspect the existing automation before changing it.
2. Update or create a cron automation. Prefer updating `auto-job-apply` over creating a duplicate.
3. Use a short scan-first prompt:

```text
Use the callback plugin's scan-job-leads workflow.

North Star: maximize qualified interview chances without spammy or unapproved applications.

Run a scheduled job lead scan for San Diego-area or San-Diego-workable remote software and AI engineering roles. Read the automation memory first, scan unread Gmail job/recruiter/status messages, current recent web results, and official FAANG career sources. Validate full current sources before staging leads. Dedupe against the job search ledger and CSV record. Do not tailor resumes, submit applications, reply to recruiters, or mark applications submitted. Return the standard scan-job-leads summary and recommend selected full-source leads for review-job-application.
```

4. After update, verify the stored prompt references `scan-job-leads` and does not depend on old `auto-job-apply` instructions except as the automation id/migration alias.

## Output

Report the automation id, status, schedule, cwd, model, and whether the prompt is scan-first.
