# Status values and notes

Write each record with `record_status(status, url, company, title, salary_range, note, date)`. For an email-sourced contact or status event (application, confirmation, rejection, recruiter message), pass the email's own date as `date` (`YYYY-MM-DD` from its Date header), so exports and `since` filters use the contact's date. Scoring, staging, skip and curation outcomes omit `date`, so they get the processing date. Also put the full source timestamp in `note`, recorded as-is with its offset. Never convert it to another time zone.

Field rules:

- `company`: employer or recruiter/client label if company is hidden.
- `title`: posting title. Keep recruiter-thread inferred titles explicit.
- `url`: canonical job URL (`http://` or `https://`) when available. For recruiter-only leads with no posting URL, leave `url` out, pass `company` and `title`, and put a stable thread descriptor in `note`.
- `salary_range`: posting/recruiter compensation range, for example `$120K-$160K` or `$75/hr W2`. Omit it when unknown; do not send the literal `Not listed`. Do not invent salary. If multiple sources disagree, explain the conflict in `note`. The ledger keeps the first range it stored and never overwrites it, so a newer range goes in `note` only.
- `status`: one value from the vocabulary below.
- `note`: recruiter thread descriptor (for leads with no posting URL), dedupe rationale, salary source if useful, fit rationale, mismatch summary, blockers, source email details, before/after scores, resume and cover letter paths, and next action. Every application or contact note starts with `Contact method: <Online|Email|Phone|Mail|Fax|In person>`.

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
- `Duplicate alert - already scored`: new email/URL matched an existing role that has no submission or outcome status yet (never record it over `Applied`, `Rejected`, etc.).
- `Closed - not scored`: posting was closed before scoring.
- `Skipped - hard blocker`: clearance, location, work authorization, or other hard blocker.
- `Skipped - not fit`: role is materially off-track for the user's software/AI target.
- `Recruiter follow-up`: recruiter thread needs user decision or reply.

Dedupe: call `find_job(url, company, title)`. It matches the URL first, then falls back to company plus title (see `matched_by`). Compare the returned stored `url` and requisition IDs first for a `company_title` or `key_title_mismatch` match. Reuse its `job_key` only when they confirm the same posting. If they prove a different posting: after a `company_title` match, record the new URL with no `job_key`; after a `key_title_mismatch` (the new URL normalizes to the old job's key), call `record_status` with no `url` (company + title only, so it gets its own job) and put the URL in `note`. A duplicate alert for a job with `ever_applied` true is not recorded again: mention it in the run summary only, so the job's latest status stays its lifecycle status. Each event's `note` holds only that event's details; earlier notes stay on their own events (`/export-ledger` with `mode="events"` shows them all).

Mismatch summary rule:

- For every scored role, include a short mismatch summary in `note`: strongest overlaps, missing keyword clusters, and why the score was high/low.
- For skipped roles, include the blocker/mismatch reason and salary if the source listed it.
