"""MCP tool `record_status`."""

import datetime
import sqlite3
from contextlib import closing

from callback.models.envelope import err, ok
from callback.models.ledger import StatusUpdate
from callback.repositories import ledger, ledger_keys
from callback.services.ledger_notes import contact_note
from callback.tools.ledger_inputs import date_error, identity_error, ledger_error


def _today_iso() -> str:
    return datetime.date.today().isoformat()  # local date, like the skills' folders


def _record_status_error(
    status: str,
    url: str | None,
    company: str | None,
    title: str | None,
    date: str | None,
    job_key: str | None,
) -> dict | None:
    if not job_key and (error := identity_error(url, company, title)):
        return error
    if not status.strip():
        return err("ledger", "invalid_status", "status must not be empty.")
    return date_error("date", date)


def record_status(
    status: str,
    url: str | None = None,
    company: str | None = None,
    title: str | None = None,
    salary_range: str | None = None,
    note: str | None = None,
    date: str | None = None,
    job_key: str | None = None,
) -> dict:
    """Add a status event (e.g. 'Applied', 'Rejected', 'Skipped - not fit') to a job in the ledger.

    Give a URL, or a company and title. Creates the job if it is new. A url without http://
    or https:// (e.g. a recruiter thread) is not a URL: it goes into the note as
    'Contact: <value>' and the job is keyed by company and title (or job_key). To record on a
    job that find_job found by company+title, pass its job_key instead (URL, company, title
    are then not needed); an unknown job_key is an error. With job_key, salary_range only
    fills empty fields. History is never overwritten; only an exact repeat (same job, status,
    date, source, and note) is ignored (recorded: false). date is YYYY-MM-DD and defaults to
    today.
    Error codes: missing_job_identity, invalid_status, invalid_date, unknown_job, ledger_error.
    """
    web_url = ledger_keys.url_or_none(url)
    if error := _record_status_error(status, web_url, company, title, date, job_key):
        return error
    update = StatusUpdate(
        status=status.strip(),
        recorded_at=date or _today_iso(),
        note=contact_note(url, note),
        source="mcp",
        job_key=job_key,
        url=web_url,
        company=company,
        title=title,
        salary_range=salary_range,
    )
    try:
        with closing(ledger.connect()) as conn:
            if job_key and not ledger.job_exists(conn, job_key):
                return err("ledger", "unknown_job", f"no job with job_key: {job_key!r}")
            added = ledger.record_status(conn, update)
    except ledger.AmbiguousJobMatchError as exc:
        return err(
            "ledger",
            "ambiguous_job",
            "Several jobs share that company and title; pass job_key from find_job.",
            retriable=False,
            data={"candidate_job_keys": list(exc.candidates)},
        )
    except (sqlite3.Error, OSError, RuntimeError, UnicodeError) as exc:
        return ledger_error(exc)
    return ok("", data={"recorded": added})
