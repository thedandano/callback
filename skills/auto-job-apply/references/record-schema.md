# Job Application Record Schema

CSV path: `<path_to_project>/Codex_Job_application_record.csv`

Required columns:

```csv
Company,Title,Recorded Date,Email Date,URL,Salary range,Status,Notes,Resume score after tailoring,Resume score before tailoring,Link to resume used,Link to cover letter used
```

Column rules:

- `Company`: employer or recruiter/client label if company is hidden.
- `Title`: posting title. Keep recruiter-thread inferred titles explicit.
- `Recorded Date`: date Codex created or updated the row.
- `Email Date`: source email timestamp. Use PT when possible, for example `2026-05-20 08:17 PT`.
- `URL`: canonical job URL when available. For recruiter-only leads, use a stable thread descriptor.
- `Salary range`: posting/recruiter compensation range, for example `$120K-$160K`, `$75/hr W2`, or `Not listed`. Do not invent salary. If multiple sources disagree, use the current employer/recruiter source and explain the conflict in `Notes`.
- `Status`: compact state from the vocabulary below.
- `Notes`: dedupe rationale, salary source if useful, fit rationale, mismatch summary, blockers, source email details, and next action.
- `Resume score after tailoring`: pi-apply tailored score, blank if not scored.
- `Resume score before tailoring`: pi-apply initial score, blank if not scored.
- `Link to resume used`: absolute path to generated PDF, blank if none.
- `Link to cover letter used`: absolute path if generated, blank if none.

Explicit status vocabulary:

- `Needs review - not applied`: score is 70+ and the user should review before submission.
- `Referral lead - ask friend`: plausible Netflix role that should pause for referral outreach before any direct application; score and tailored artifacts may be present even below the normal 70 threshold.
- `Applied`: user explicitly approved and application was submitted.
- `Already applied - confirmation recorded`: Gmail or artifact confirms prior submission.
- `Rejected`: rejection email or portal status confirms no longer moving forward.
- `Scored - below threshold`: scored below 70.
- `Needs pi-apply score - not applied`: role passed the location/plausibility gate but pi-apply scoring was not available in the current session.
- `Needs source - manual lookup`: role came from an email, alert card, search result, or blocked/partial page, and no full current source JD was available. Do not score from the snippet; the user needs to find/open the full JD manually.
- `Rescored - not applied`: existing row was rescored only.
- `Duplicate alert - already scored`: new email/URL matched an existing role.
- `Closed - not scored`: posting was closed before scoring.
- `Skipped - hard blocker`: clearance, location, work authorization, or other hard blocker.
- `Skipped - not fit`: role is materially off-track for the user's software/AI target.
- `Recruiter follow-up`: recruiter thread needs user decision or reply.

Dedupe order:

1. Exact URL.
2. Exact Title.
3. Company plus similar Title.

When deduping by title/company with a different URL, update the existing row's `Email Date` only if the new email is the active source for the latest status. Otherwise append the new email detail to `Notes`.

Mismatch summary rule:

- For every scored role, include a short mismatch summary in `Notes`: strongest overlaps, missing keyword clusters, and why the score was high/low.
- For skipped roles, include the blocker/mismatch reason and salary if the source listed it.
