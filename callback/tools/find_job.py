"""MCP tool `find_job`."""

import sqlite3
from contextlib import closing

from callback.models.envelope import ok
from callback.repositories import ledger, ledger_keys
from callback.tools.ledger_inputs import identity_error, ledger_error


def find_job(url: str | None = None, company: str | None = None, title: str | None = None) -> dict:
    """Check whether a job is already in callback's ledger (for dedupe before scoring or applying).

    Pass the posting URL, or company and title for a pasted job description with no URL. A
    url without http:// or https:// (e.g. a recruiter thread) is ignored for the lookup. A job
    seen under a different URL is still found when company and title match, but that is a
    weaker match (the same title can be two real postings): check matched_by ('key',
    'key_title_mismatch' when the URL matches but the stored title differs or is missing,
    'company_title', or
    null) and confirm anything but 'key' before skipping. Returns found, job_key, company,
    title, stored URL, latest status with its date, and ever_applied (whether any status proves
    submission). To record a status on the job found by company+title, pass its job_key to
    record_status. When not found or the match is weak,
    and a company is given, company_jobs lists that company's other jobs (up to 20, newest
    first; each with job_key, url, title, status, status_date, ever_applied) so you can spot a
    similar title or a requisition id in a job_key URL.
    Error codes: missing_job_identity, ledger_error.
    """
    url = ledger_keys.url_or_none(url)
    if error := identity_error(url, company, title):
        return error
    try:
        with closing(ledger.connect()) as conn:
            return ok("", data=ledger.find_job(conn, url=url, company=company, title=title))
    except (sqlite3.Error, OSError, RuntimeError, UnicodeError) as exc:
        return ledger_error(exc)
