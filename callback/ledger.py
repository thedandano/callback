"""Global application ledger: one SQLite file (`paths.ledger_path()`) for every job seen.

Holds jobs, tailoring runs, and status events. Opens in WAL mode so a reader never blocks the
writer, and status events are append-only: a repeat of the same event is ignored, never rewritten.
"""

from __future__ import annotations

import json
import sqlite3
from pathlib import Path
from urllib.parse import parse_qsl, urlencode, urlsplit, urlunsplit

from pydantic import BaseModel, ConfigDict

from callback import paths

_BUSY_TIMEOUT_S = 5.0
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
        return (self.keywords or {}).get("company")

    @property
    def title(self) -> str | None:
        return (self.keywords or {}).get("title")


def normalize_url(url: str) -> str:
    """Canonical form of a posting URL: https, lowercase host, no fragment or trailing slash.

    Keeps only the query parameters that name the posting (`_JOB_ID_PARAMS`). A board that
    names its job id in another parameter needs that name added there.
    """
    parts = urlsplit(url.strip())
    scheme = "https" if parts.scheme.lower() in ("http", "https") else parts.scheme.lower()
    query = urlencode(sorted((k, v) for k, v in parse_qsl(parts.query) if k in _JOB_ID_PARAMS))
    return urlunsplit((scheme, parts.netloc.lower(), parts.path.rstrip("/"), query, ""))


def job_key(url: str | None, company: str | None, title: str | None) -> str:
    """URL postings key on the normalized URL; pasted job descriptions have none, so use
    company + title.

    ponytail: two different pasted postings with the same company and title share one job.
    Add a JD-text hash here if that ever merges postings that should stay apart.
    """
    if url:
        return normalize_url(url)
    return f"pasted:{paths.slug(company, title)}"


def connect(path: Path | None = None) -> sqlite3.Connection:
    path = path or paths.ledger_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(str(path), timeout=_BUSY_TIMEOUT_S)
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA foreign_keys=ON")
    conn.executescript(_SCHEMA)
    return conn


def upsert_job(
    conn: sqlite3.Connection,
    *,
    url: str | None,
    company: str | None,
    title: str | None,
    seen_at: str,
    salary_range: str | None = None,
) -> str:
    key = job_key(url, company, title)
    stored_url = normalize_url(url) if url else None
    with conn:
        conn.execute(_UPSERT_JOB, (key, stored_url, company, title, salary_range, seen_at))
    return key


def record_run(conn: sqlite3.Connection, run: RunRecord) -> None:
    key = upsert_job(
        conn, url=run.jd_url, company=run.company, title=run.title, seen_at=run.timestamp
    )
    with conn:
        conn.execute(
            _UPSERT_RUN,
            (
                run.session_id,
                key,
                run.timestamp,
                run.jd_text,
                json.dumps(run.keywords),
                run.tailored_resume_text,
                run.pdf_path,
                run.render_page_count,
                json.dumps(run.render_warnings),
                json.dumps(run.scores),
                json.dumps(run.uncovered_skills),
                json.dumps(run.outcome),
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
