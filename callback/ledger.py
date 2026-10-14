"""Global application ledger: one SQLite file (`paths.ledger_path()`) for every job seen.

Holds jobs, tailoring runs, and status events. Opens in WAL mode so a reader never blocks the
writer, and status events are append-only: a repeat of the same event is ignored, never rewritten.
"""

from __future__ import annotations

import hashlib
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
# Query parameters that only say where a click came from, compared lowercase. Everything else in
# the query string is kept, because boards name the posting in many different parameters
# (Taleo `job`, SuccessFactors `career_job_req_id`, LinkedIn `currentJobId`, ...).
_TRACKING_PARAM_PREFIXES = ("utm_",)
_TRACKING_PARAMS = frozenset(
    {
        "gh_src",
        "refid",
        "ref_id",
        "trk",
        "trackingid",
        "tracking_id",
        "lever-source",
        "lever-origin",
        "fbclid",
        "gclid",
        "mc_cid",
        "mc_eid",
        "vjs",
        "tk",
        "_ga",
        "igshid",
        "si",
        "refererurl",
        "referrer",
        "cmp",
        "campaign",
        "medium",
        "sharedid",
    }
)
_JD_HASH_CHARS = 8

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
    source TEXT NOT NULL
);
"""

_CREATE_STATUS_EVENT_IDENTITY_INDEX = """
CREATE UNIQUE INDEX IF NOT EXISTS status_events_identity
ON status_events (job_key, status, recorded_at, source, ifnull(note, ''))
"""

_CREATE_STATUS_EVENTS_TABLE = """
CREATE TABLE status_events (
    id INTEGER PRIMARY KEY,
    job_key TEXT NOT NULL REFERENCES jobs(job_key),
    status TEXT NOT NULL,
    recorded_at TEXT NOT NULL,
    note TEXT,
    source TEXT NOT NULL
)
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

    Drops the query parameters that only track the click (`_TRACKING_PARAMS`, any `utm_*`),
    compared case-insensitively, and keeps the rest in sorted order. A board that adds a new
    tracking parameter needs it added there, or its links split into two keys. Fragments are dropped
    unless they look like a route ("#/job/1", "#!/job/1"). A value that cannot be parsed is
    logged and kept as typed.

    ponytail: `www.` is kept, so "www.x.com/a" and "x.com/a" get two keys. Strip it here if
    that ever splits one posting in two.
    """
    stripped = url.strip()
    try:
        outer = urlsplit(stripped)
        if outer.scheme.lower() in _DEFAULT_PORTS and outer.netloc:
            candidate = stripped
        elif stripped.startswith("//"):
            candidate = f"https:{stripped}"
        else:
            candidate = f"https://{stripped}"
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
    query = _normalized_query(parts.query)
    fragment = _normalized_route_fragment(parts.fragment)
    return urlunsplit((scheme, netloc, parts.path.rstrip("/"), query, fragment))


def _normalized_query(query: str) -> str:
    return urlencode(
        sorted((key, value) for key, value in parse_qsl(query) if not _is_tracking(key))
    )


def _normalized_route_fragment(fragment: str) -> str:
    if not fragment.startswith(_ROUTE_FRAGMENT_PREFIXES):
        return ""
    route = urlsplit(fragment)
    return urlunsplit(("", "", route.path.rstrip("/"), _normalized_query(route.query), ""))


def _is_tracking(param: str) -> bool:
    name = param.lower()
    return name.startswith(_TRACKING_PARAM_PREFIXES) or name in _TRACKING_PARAMS


def _clean_url(url: str | None) -> str | None:
    """Normalized URL, or None when there is no URL (missing or blank)."""
    if url is None or not url.strip():
        return None
    return normalize_url(url)


def job_key(
    url: str | None, company: str | None, title: str | None, jd_text: str | None = None
) -> str:
    """URL postings key on the normalized URL; pasted job descriptions have none, so use
    company + title.

    When company or title is missing and the JD text is known, a short hash of the text is
    added so unlabeled pasted jobs do not all merge into one `pasted:job` row.

    ponytail: two different pasted postings with the same company and title share one job.
    """
    cleaned = _clean_url(url)
    if cleaned:
        return cleaned
    slug = paths.slug(company, title)
    if (company and title) or not jd_text:
        return f"pasted:{slug}"
    digest = hashlib.sha1(jd_text.encode("utf-8")).hexdigest()[:_JD_HASH_CHARS]
    _log.info(json.dumps({"event": "ledger_key_from_jd_text", "slug": slug, "hash": digest}))
    return f"pasted:{slug}-{digest}"


def connect(path: Path | None = None) -> sqlite3.Connection:
    """Open the ledger. WAL needs a local filesystem; a network drive will fail here."""
    path = path or paths.ledger_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(str(path), timeout=_BUSY_TIMEOUT_S)
    try:
        conn.execute("PRAGMA journal_mode=WAL")
        conn.execute("PRAGMA foreign_keys=ON")
        conn.executescript(_SCHEMA)
        _migrate_legacy_status_event_identity(conn)
        conn.execute(_CREATE_STATUS_EVENT_IDENTITY_INDEX)
    except sqlite3.Error as exc:
        conn.close()
        _log.warning(
            json.dumps({"event": "ledger_open_failed", "path": str(path), "error": str(exc)})
        )
        raise
    return conn


def _migrate_legacy_status_event_identity(conn: sqlite3.Connection) -> None:
    if not _has_legacy_status_event_identity(conn):
        return
    with conn:
        conn.execute("ALTER TABLE status_events RENAME TO status_events_legacy")
        conn.execute(_CREATE_STATUS_EVENTS_TABLE)
        conn.execute(
            "INSERT INTO status_events (id, job_key, status, recorded_at, note, source) "
            "SELECT id, job_key, status, recorded_at, note, source FROM status_events_legacy"
        )
        conn.execute("DROP TABLE status_events_legacy")
    _log.warning(json.dumps({"event": "ledger_status_events_migrated"}))


def _has_legacy_status_event_identity(conn: sqlite3.Connection) -> bool:
    for _, index_name, is_unique, *_ in conn.execute("PRAGMA index_list(status_events)"):
        if is_unique and _index_columns(conn, index_name) == ["job_key", "status", "recorded_at"]:
            return True
    return False


def _index_columns(conn: sqlite3.Connection, index_name: str) -> list[str]:
    escaped_name = index_name.replace("'", "''")
    rows = conn.execute(f"PRAGMA index_info('{escaped_name}')")
    return [row[2] for row in rows]


def _upsert_job(
    conn: sqlite3.Connection,
    *,
    url: str | None,
    company: str | None,
    title: str | None,
    seen_at: str,
    salary_range: str | None,
    jd_text: str | None = None,
) -> str:
    """Insert or merge a job row without committing; callers own the transaction."""
    key = job_key(url, company, title, jd_text)
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
    jd_text: str | None = None,
) -> str:
    with conn:
        return _upsert_job(
            conn,
            url=url,
            company=company,
            title=title,
            seen_at=seen_at,
            salary_range=salary_range,
            jd_text=jd_text,
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
            salary_range=_salary_range(run.keywords),
            jd_text=run.jd_text,
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


def _salary_range(keywords: dict | None) -> str | None:
    minimum = _text_or_number_field(keywords, "pay_range_min")
    maximum = _text_or_number_field(keywords, "pay_range_max")
    if minimum and maximum:
        return f"{minimum}-{maximum}"
    return minimum or maximum


def _text_or_number_field(keywords: dict | None, name: str) -> str | None:
    value = (keywords or {}).get(name)
    if isinstance(value, str) and value.strip():
        return value.strip()
    if isinstance(value, int | float) and not isinstance(value, bool):
        if isinstance(value, float) and value.is_integer():
            return str(int(value))
        return str(value)
    return None


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
