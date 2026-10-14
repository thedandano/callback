# Status values and notes

Write each record with `record_status(status, url, company, title, salary_range, note, date)`. Put the email date in `note`, recorded as-is with the offset from its Date header. Never convert it to another time zone.

Field rules:

- `company`: employer or recruiter/client label if company is hidden.
- `title`: posting title. Keep recruiter-thread inferred titles explicit.
- `url`: canonical job URL (`http://` or `https://`) when available. For recruiter-only leads with no posting URL, leave `url` out, pass `company` and `title`, and put a stable thread descriptor in `note`.
- `salary_range`: posting/recruiter compensation range, for example `$120K-$160K`, `$75/hr W2`, or `Not listed`. Do not invent salary. If multiple sources disagree, use the current employer/recruiter source and explain the conflict in `note`.
- `status`: one value from the vocabulary below.
- `note`: recruiter thread descriptor (for leads with no posting URL), dedupe rationale, salary source if useful, fit rationale, mismatch summary, blockers, source email details, before/after scores, resume and cover letter paths, and next action.

Explicit status vocabulary:

- `Needs review - not applied`: score is 70+ and the user should review before submission.
- `Referral lead - ask friend`: plausible Acme role that should pause for referral outreach before any direct application; score and tailored artifacts may be present even below the normal 70 threshold.
- `Applied`: user explicitly approved and application was submitted.
- `Already applied - confirmation recorded`: Gmail or artifact confirms prior submission.
- `Rejected`: rejection email or portal status confirms no longer moving forward.
- `Scored - below threshold`: scored below 70.
- `Needs callback score - not applied`: role passed the location/plausibility gate but callback scoring was not available in the current session.
- `Needs source - manual lookup`: role came from an email, alert card, search result, or blocked/partial page, and no full current source JD was available. Do not score from the snippet; the user needs to find/open the full JD manually.
- `Rescored - not applied`: existing row was rescored only.
- `Duplicate alert - already scored`: new email/URL matched an existing role.
- `Closed - not scored`: posting was closed before scoring.
- `Skipped - hard blocker`: clearance, location, work authorization, or other hard blocker.
- `Skipped - not fit`: role is materially off-track for the user's software/AI target.
- `Recruiter follow-up`: recruiter thread needs user decision or reply.

Dedupe: call `find_job(url, company, title)`. It matches the URL first, then falls back to company plus title (see `matched_by`). When it matches by company and title, pass its `job_key` to `record_status` so the status lands on the existing job. When the new email is the active source for the latest status, say so in `note`; otherwise append the new email detail to `note`.

Mismatch summary rule:

- For every scored role, include a short mismatch summary in `note`: strongest overlaps, missing keyword clusters, and why the score was high/low.
- For skipped roles, include the blocker/mismatch reason and salary if the source listed it.
