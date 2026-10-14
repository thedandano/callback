"""Global application ledger: one SQLite file (`paths.ledger_path()`) for every job seen.

Holds jobs, tailoring runs, and status events. Opens in WAL mode so a reader never blocks the
writer, and status events are append-only: a repeat of the same event is ignored, never rewritten.
"""

from __future__ import annotations

import json
import logging
import sqlite3
from pathlib import Path
from urllib.parse import parse_qsl, urlencode, urlsplit, urlunsplit

from pydantic import BaseModel, ConfigDict

from callback import paths

_log = logging.getLogger(__name__)

_BUSY_TIMEOUT_S = 5.0
_DEFAULT_PORTS = {"http": ":80", "https": ":443"}
_ROUTE_FRAGMENT_PREFIXES = ("/", "!")
# Query parameters that name the posting itself (Greenhouse, Indeed, Workday/Phenom, Lever-style,
# ZipRecruiter). Everything else in the query string is tracking noise.
_JOB_ID_PARAMS = frozenset(
    {"gh_jid", "jk", "jid", "pid", "jobId", "job_id", "jobListingId", "guid", "id", "match_token"}
)

_SCHEMA = """
CREATE TABLE IF NOT EXISTS jobs (
    job_key TEXT PRIMARY KEY,
    url TEXT,
    company TEXT,
    title TEXT,
    salary_range TEXT,
    first_seen TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS runs (
    session_id TEXT PRIMARY KEY,
    job_key TEXT NOT NULL REFERENCES jobs(job_key),
    finalized_at TEXT NOT NULL,
    jd_text TEXT,
    keywords TEXT,
    tailored_resume_text TEXT,
    pdf_path TEXT,
    render_page_count INTEGER,
    render_warnings TEXT,
    scores TEXT,
    uncovered_skills TEXT,
    outcome TEXT
);
CREATE TABLE IF NOT EXISTS status_events (
    id INTEGER PRIMARY KEY,
    job_key TEXT NOT NULL REFERENCES jobs(job_key),
    status TEXT NOT NULL,
    recorded_at TEXT NOT NULL,
    note TEXT,
    source TEXT NOT NULL,
    UNIQUE (job_key, status, recorded_at)
);
"""

_UPSERT_JOB = """
INSERT INTO jobs (job_key, url, company, title, salary_range, first_seen)
VALUES (?, ?, ?, ?, ?, ?)
ON CONFLICT(job_key) DO UPDATE SET
    url = COALESCE(jobs.url, excluded.url),
    company = COALESCE(jobs.company, excluded.company),
    title = COALESCE(jobs.title, excluded.title),
    salary_range = COALESCE(jobs.salary_range, excluded.salary_range),
    first_seen = CASE
        WHEN excluded.first_seen = '' THEN jobs.first_seen
        WHEN jobs.first_seen = '' THEN excluded.first_seen
        ELSE MIN(jobs.first_seen, excluded.first_seen)
    END
"""

_UPSERT_RUN = """
INSERT INTO runs (session_id, job_key, finalized_at, jd_text, keywords, tailored_resume_text,
                  pdf_path, render_page_count, render_warnings, scores, uncovered_skills, outcome)
VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
ON CONFLICT(session_id) DO UPDATE SET
    job_key = excluded.job_key,
    finalized_at = excluded.finalized_at,
    jd_text = excluded.jd_text,
    keywords = excluded.keywords,
    tailored_resume_text = excluded.tailored_resume_text,
    pdf_path = excluded.pdf_path,
    render_page_count = excluded.render_page_count,
    render_warnings = excluded.render_warnings,
    scores = excluded.scores,
    uncovered_skills = excluded.uncovered_skills,
    outcome = excluded.outcome
"""


class RunRecord(BaseModel):
    """One tailoring run, shaped like the old <session_id>.json archive."""

    model_config = ConfigDict(extra="ignore")

    session_id: str
    timestamp: str
    jd_url: str | None = None
    jd_text: str | None = None
    keywords: dict | None = None
    tailored_resume_text: str | None = None
    pdf_path: str | None = None
    render_page_count: int | None = None
    render_warnings: list = []
    scores: dict = {}
    uncovered_skills: list = []
    outcome: dict = {}

    @property
    def company(self) -> str | None:
        return _text_field(self.keywords, "company")

    @property
    def title(self) -> str | None:
        return _text_field(self.keywords, "title")


def _text_field(keywords: dict | None, name: str) -> str | None:
    value = (keywords or {}).get(name)
    if isinstance(value, str) and value.strip():
        return value.strip()
    return None


def normalize_url(url: str) -> str:
    """Canonical form of a posting URL: https, lowercase host, no default port, no trailing slash.

    Keeps only the query parameters that name the posting (`_JOB_ID_PARAMS`). A board that
    names its job id in another parameter needs that name added there. Fragments are dropped
    unless they look like a route ("#/job/1", "#!/job/1"). A value that cannot be parsed is
    logged and kept as typed.

    ponytail: `www.` is kept, so "www.x.com/a" and "x.com/a" get two keys. Strip it here if
    that ever splits one posting in two.
    """
    stripped = url.strip()
    candidate = stripped if "://" in stripped else f"https://{stripped}"
    try:
        parts = urlsplit(candidate)
    except ValueError as exc:
        _log.warning(
            json.dumps({"event": "ledger_url_unparsed", "url": stripped, "error": str(exc)})
        )
        return stripped
    scheme = parts.scheme.lower()
    netloc = parts.netloc.lower().removesuffix(_DEFAULT_PORTS.get(scheme, "\0"))
    if scheme == "http":
        scheme = "https"
    query = urlencode(sorted((k, v) for k, v in parse_qsl(parts.query) if k in _JOB_ID_PARAMS))
    fragment = parts.fragment if parts.fragment.startswith(_ROUTE_FRAGMENT_PREFIXES) else ""
    return urlunsplit((scheme, netloc, parts.path.rstrip("/"), query, fragment))


def _clean_url(url: str | None) -> str | None:
    """Normalized URL, or None when there is no URL (missing or blank)."""
    if url is None or not url.strip():
        return None
    return normalize_url(url)


def job_key(url: str | None, company: str | None, title: str | None) -> str:
    """URL postings key on the normalized URL; pasted job descriptions have none, so use
    company + title.

    ponytail: two different pasted postings with the same company and title share one job.
    Add a JD-text hash here if that ever merges postings that should stay apart.
    """
    cleaned = _clean_url(url)
    if cleaned:
        return cleaned
    return f"pasted:{paths.slug(company, title)}"


def connect(path: Path | None = None) -> sqlite3.Connection:
    """Open the ledger. WAL needs a local filesystem; a network drive will fail here."""
    path = path or paths.ledger_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(str(path), timeout=_BUSY_TIMEOUT_S)
    try:
        conn.execute("PRAGMA journal_mode=WAL")
        conn.execute("PRAGMA foreign_keys=ON")
        conn.executescript(_SCHEMA)
    except sqlite3.Error as exc:
        conn.close()
        _log.warning(
            json.dumps({"event": "ledger_open_failed", "path": str(path), "error": str(exc)})
        )
        raise
    return conn


def _upsert_job(
    conn: sqlite3.Connection,
    *,
    url: str | None,
    company: str | None,
    title: str | None,
    seen_at: str,
    salary_range: str | None,
) -> str:
    """Insert or merge a job row without committing; callers own the transaction."""
    key = job_key(url, company, title)
    conn.execute(_UPSERT_JOB, (key, _clean_url(url), company, title, salary_range, seen_at))
    return key


def upsert_job(
    conn: sqlite3.Connection,
    *,
    url: str | None,
    company: str | None,
    title: str | None,
    seen_at: str,
    salary_range: str | None = None,
) -> str:
    with conn:
        return _upsert_job(
            conn,
            url=url,
            company=company,
            title=title,
            seen_at=seen_at,
            salary_range=salary_range,
        )


def _json_or_null(value: object) -> str | None:
    return None if value is None else json.dumps(value)


def record_run(conn: sqlite3.Connection, run: RunRecord) -> None:
    """Save a run and its job in one transaction.

    ponytail: a retry whose URL, company or title changed re-points the run to a new job and
    can leave the old job with no runs. Harmless for dedupe; prune orphans if it ever matters.
    """
    # Serialize first so bad data fails before anything is written.
    blobs = (
        _json_or_null(run.keywords),
        json.dumps(run.render_warnings),
        json.dumps(run.scores),
        json.dumps(run.uncovered_skills),
        json.dumps(run.outcome),
    )
    with conn:
        key = _upsert_job(
            conn,
            url=run.jd_url,
            company=run.company,
            title=run.title,
            seen_at=run.timestamp,
            salary_range=None,
        )
        conn.execute(
            _UPSERT_RUN,
            (
                run.session_id,
                key,
                run.timestamp,
                run.jd_text,
                blobs[0],
                run.tailored_resume_text,
                run.pdf_path,
                run.render_page_count,
                *blobs[1:],
            ),
        )


def add_status(
    conn: sqlite3.Connection,
    *,
    job_key: str,
    status: str,
    recorded_at: str,
    note: str | None,
    source: str,
) -> bool:
    """Append a status event. Returns True if a new row was added, False for an exact repeat."""
    with conn:
        cursor = conn.execute(
            "INSERT OR IGNORE INTO status_events (job_key, status, recorded_at, note, source) "
            "VALUES (?, ?, ?, ?, ?)",
            (job_key, status, recorded_at, note, source),
        )
    return cursor.rowcount == 1
