"""Global application ledger: one SQLite file (`paths.ledger_path()`) for every job seen.

Holds jobs, tailoring runs, and status events. Opens in WAL mode so a reader never blocks the
writer, and status events are append-only: a repeat of the same event is ignored, never rewritten.
"""

from __future__ import annotations

import hashlib
import json
import logging
import re
import sqlite3
from datetime import UTC, date, datetime
from pathlib import Path
from typing import NamedTuple
from urllib.parse import parse_qsl, urlencode, urlsplit, urlunsplit

from pydantic import BaseModel, ConfigDict

from callback import paths

_log = logging.getLogger(__name__)

_BUSY_TIMEOUT_S = 5.0
_DEFAULT_PORTS = {"http": ":80", "https": ":443"}
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
_NAME_SEPARATOR = "\x1f"
_SALARY_PLACEHOLDERS = frozenset({"", "not listed", "n/a", "unknown", "ambiguous", "-", "tbd"})
_PLAIN_DATE = re.compile(r"[0-9]{4}-[0-9]{2}-[0-9]{2}")

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

_UPSERT_JOB = """
INSERT INTO jobs (job_key, url, company, title, salary_range, first_seen)
VALUES (?, ?, ?, ?, ?, ?)
ON CONFLICT(job_key) DO UPDATE SET
    url = COALESCE(NULLIF(jobs.url, ''), excluded.url),
    company = COALESCE(NULLIF(jobs.company, ''), excluded.company),
    title = COALESCE(NULLIF(jobs.title, ''), excluded.title),
    salary_range = COALESCE(NULLIF(jobs.salary_range, ''), excluded.salary_range),
    first_seen = CASE
        WHEN excluded.first_seen = '' THEN jobs.first_seen
        WHEN jobs.first_seen = '' THEN excluded.first_seen
        WHEN julianday(excluded.first_seen) IS NULL OR julianday(jobs.first_seen) IS NULL
            THEN MIN(jobs.first_seen, excluded.first_seen)
        WHEN julianday(excluded.first_seen) < julianday(jobs.first_seen)
            THEN excluded.first_seen
        ELSE jobs.first_seen
    END
"""

_FILL_JOB_FROM_URL_JOB = """
UPDATE jobs SET
    company = COALESCE(NULLIF(company, ''), (SELECT company FROM jobs WHERE job_key = ?)),
    title = COALESCE(NULLIF(title, ''), (SELECT title FROM jobs WHERE job_key = ?)),
    salary_range = COALESCE(
        NULLIF(salary_range, ''), (SELECT salary_range FROM jobs WHERE job_key = ?)
    ),
    first_seen = CASE
        WHEN first_seen = '' THEN (SELECT first_seen FROM jobs WHERE job_key = ?)
        ELSE MIN(
            first_seen,
            COALESCE(NULLIF((SELECT first_seen FROM jobs WHERE job_key = ?), ''), first_seen)
        )
    END
WHERE job_key = ?
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

_INSERT_RUN_IF_ABSENT = """
INSERT INTO runs (session_id, job_key, finalized_at, jd_text, keywords, tailored_resume_text,
                  pdf_path, render_page_count, render_warnings, scores, uncovered_skills, outcome)
VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
ON CONFLICT(session_id) DO NOTHING
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


class JobNameMatch(NamedTuple):
    """The matching job key, plus every same-name candidate when it is ambiguous."""

    job_key: str | None
    candidates: tuple[str, ...]


class AmbiguousJobMatchError(Exception):
    """More than one job shares the company and title; the caller must pass a job_key."""

    def __init__(self, candidates: tuple[str, ...]):
        self.candidates = candidates
        super().__init__(f"ambiguous company+title match: {candidates}")


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
    unless they hold a recognized route ("#/job/1", "#!/job/1", Gmail "#all/<id>").
    A value that cannot be parsed is logged and kept as typed.

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
    fragment = _normalized_route_fragment(parts.fragment, parts.hostname)
    return urlunsplit((scheme, netloc, parts.path.rstrip("/"), query, fragment))


def _normalized_query(query: str) -> str:
    return urlencode(
        sorted(
            (key, value)
            for key, value in parse_qsl(query, keep_blank_values=True)
            if not _is_tracking(key)
        )
    )


def _normalized_route_fragment(fragment: str, hostname: str | None) -> str:
    """Keep hash routes (`#/x`, `#!/x`) and Gmail message ids; drop descriptive fragments."""
    prefix, body = ("!", fragment[1:]) if fragment.startswith("!/") else ("", fragment)
    route = urlsplit(body)
    if body.startswith("/"):
        path = route.path.rstrip("/")
        return prefix + urlunsplit(("", "", path, _normalized_query(route.query), ""))
    if hostname != "mail.google.com" or not _is_gmail_message_path(route.path):
        return ""
    return urlunsplit(("", "", route.path, _normalized_query(route.query), ""))


def _is_gmail_message_path(path: str) -> bool:
    mailbox, separator, message_id = path.partition("/")
    return mailbox in {"all", "inbox"} and bool(separator and message_id and "/" not in message_id)


def url_or_none(value: str | None) -> str | None:
    """The stripped value if it is an http(s) URL with a host, else None (a thread descriptor)."""
    text = (value or "").strip()
    try:
        parts = urlsplit(text)
        hostname, _port = parts.hostname, parts.port
    except ValueError as exc:
        _log.warning(json.dumps({"event": "ledger_url_unparseable", "error": str(exc)}))
        return None
    if parts.scheme.lower() not in {"http", "https"} or not hostname:
        return None
    return text if not any(character.isspace() for character in hostname) else None


def _is_tracking(param: str) -> bool:
    name = param.lower()
    return name.startswith(_TRACKING_PARAM_PREFIXES) or name in _TRACKING_PARAMS


def _clean_url(url: str | None) -> str | None:
    """Normalized URL, or None when there is no URL (missing or blank)."""
    if url is None or not url.strip():
        return None
    return normalize_url(url)


def _norm_text(value: str | None) -> str:
    """Casefolded text with runs of whitespace collapsed, so case and spacing never split keys."""
    return " ".join((value or "").casefold().split())


def _short_hash(text: str) -> str:
    return hashlib.sha1(text.encode("utf-8")).hexdigest()[:_JD_HASH_CHARS]


def _optional_text(value: str | None) -> str | None:
    """Strip optional metadata, storing blank values as SQL NULL."""
    text = (value or "").strip()
    return text or None


def job_key(
    url: str | None, company: str | None, title: str | None, jd_text: str | None = None
) -> str:
    """URL postings key on the normalized URL; pasted job descriptions have none, so use
    company + title, folded for case and spacing.

    The key ends in a short hash of the folded pair joined by a separator that cannot be
    typed in a name, so ("Meta Platforms", "Engineer") and ("Meta", "Platforms Engineer")
    stay apart. When company or title is missing and the JD text is known, a short hash of
    the text is used instead, so unlabeled pasted jobs do not all merge into one row.

    ponytail: two different pasted postings with the same company and title share one job.
    """
    cleaned = _clean_url(url)
    company = _optional_text(company)
    title = _optional_text(title)
    if cleaned:
        return cleaned
    folded_company, folded_title = _norm_text(company), _norm_text(title)
    slug = paths.slug(folded_company, folded_title)
    if (folded_company and folded_title) or not jd_text:
        pair = f"{folded_company}{_NAME_SEPARATOR}{folded_title}"
        return f"pasted:{slug}-{_short_hash(pair)}"
    digest = _short_hash(jd_text)
    _log.info(json.dumps({"event": "ledger_key_from_jd_text", "slug": slug, "hash": digest}))
    return f"pasted:{slug}-{digest}"


def connect(path: Path | None = None) -> sqlite3.Connection:
    """Open the ledger. WAL needs a local filesystem; a network drive will fail here."""
    path = path or paths.ledger_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(str(path), timeout=_BUSY_TIMEOUT_S)
    try:
        conn.create_function("norm_text", 1, _sql_norm_text, deterministic=True)
        conn.execute("PRAGMA journal_mode=WAL")
        conn.execute("PRAGMA foreign_keys=ON")
        conn.executescript(_SCHEMA)
        conn.execute(_CREATE_STATUS_EVENT_IDENTITY_INDEX)
    except sqlite3.Error as exc:
        conn.close()
        _log.warning(
            json.dumps({"event": "ledger_open_failed", "path": str(path), "error": str(exc)})
        )
        raise
    return conn


def _sql_norm_text(value: object) -> str | None:
    """SQL `norm_text`: casefold and collapse text for company/title lookup; non-text gives NULL."""
    if not isinstance(value, str):
        return None
    return _norm_text(value)


def canonical_timestamp(value: str) -> str:
    """UTC ISO form of a timestamp, so text and time order agree.

    A time with no offset is read as UTC. Plain `YYYY-MM-DD` dates and blanks come back stripped;
    text that is not ISO, or that overflows when converted to UTC, comes back as given and logs
    a warning.
    """
    stripped = value.strip()
    try:
        if not stripped or (_PLAIN_DATE.fullmatch(stripped) and date.fromisoformat(stripped)):
            return stripped
        parsed = datetime.fromisoformat(stripped)
        if parsed.tzinfo is None:
            parsed = parsed.replace(tzinfo=UTC)
        return parsed.astimezone(UTC).isoformat()
    except (ValueError, OverflowError):
        _log.warning(json.dumps({"event": "ledger_timestamp_unparsed", "value": value}))
        return value


def clean_salary(value: str | None) -> str | None:
    """The salary text, or None when it is blank or a placeholder such as `Not listed`."""
    folded = _norm_text(value)
    return None if folded in _SALARY_PLACEHOLDERS else (value or "").strip()


def _upsert_job(
    conn: sqlite3.Connection,
    *,
    url: str | None,
    company: str | None,
    title: str | None,
    seen_at: str,
    salary_range: str | None,
    jd_text: str | None = None,
    key: str | None = None,
) -> str:
    """Insert or merge a job row without committing; callers own the transaction.

    `key` overrides the computed job key; the run recorders use it to attach to an existing job.
    Blank text and salary placeholders are stored as NULL so a later call can fill them.
    """
    company = _optional_text(company)
    title = _optional_text(title)
    salary_range = clean_salary(salary_range) or None
    key = key or job_key(url, company, title, jd_text)
    conn.execute(
        _UPSERT_JOB,
        (
            key,
            _clean_url(url),
            company,
            title,
            salary_range,
            canonical_timestamp(seen_at),
        ),
    )
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

    A session already recorded keeps its job on a retry; the retry's metadata only fills that
    job's empty fields.
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
        key = _upsert_run_job(conn, run)
        conn.execute(
            _UPSERT_RUN,
            (
                run.session_id,
                key,
                canonical_timestamp(run.timestamp),
                run.jd_text,
                blobs[0],
                run.tailored_resume_text,
                run.pdf_path,
                run.render_page_count,
                *blobs[1:],
            ),
        )


def record_imported_run_if_absent(conn: sqlite3.Connection, run: RunRecord) -> bool:
    """Insert an imported run once without changing a live run with the same session id.

    The check and the insert share one transaction, and a run that exists leaves its job alone.
    """
    blobs = _run_blobs(run)
    with conn:
        if not conn.in_transaction:
            conn.execute("BEGIN IMMEDIATE")
        if _run_exists(conn, run.session_id):
            return False
        key = _upsert_run_job(conn, run)
        cursor = conn.execute(_INSERT_RUN_IF_ABSENT, _run_values(run, key, blobs))
    return cursor.rowcount == 1


def _upsert_run_job(conn: sqlite3.Connection, run: RunRecord) -> str:
    """Upsert the run's job.

    A session already in `runs` stays on its job (a retry). An existing URL-keyed job wins over
    a same-name pasted job so scores stay with that URL's history. Otherwise a new run with no
    URL may join the one same-name job that has no runs; a new run with a URL joins a pasted job
    carrying it (or a URL-less same-name job).
    """
    existing = conn.execute(
        "SELECT job_key FROM runs WHERE session_id = ?", (run.session_id,)
    ).fetchone()
    if existing:
        key = existing[0]
    else:
        cleaned = _clean_url(run.jd_url)
        key = cleaned if cleaned and job_exists(conn, cleaned) else None
        if key is None:
            key = _same_name_job_key(conn, run)
        if key is None and cleaned:
            key = _pasted_job_with_url(conn, cleaned)
    return _upsert_job(
        conn,
        url=run.jd_url,
        company=run.company,
        title=run.title,
        seen_at=run.timestamp,
        salary_range=_salary_range(run.keywords),
        jd_text=run.jd_text,
        key=key,
    )


def _same_name_job_key(conn: sqlite3.Connection, run: RunRecord) -> str | None:
    """Key of the one same-name job a run belongs to (scan-then-tailor), else None.

    Joins when company and title match exactly one job that has no other runs. A run with a
    URL still joins when that job's stored URL is empty or already the same URL, so Applied on
    a pasted row and the later finalize score stay on one job. A same-name job with a different
    URL is left alone. A job that already has runs may be a different posting, so the run keeps
    its own key and the possible twin is logged.
    """
    if not (run.company and run.title):
        return None
    cleaned = _clean_url(run.jd_url)
    match = job_key_by_name(conn, run.company, run.title)
    own = job_key(cleaned, run.company, run.title, run.jd_text)
    if len(match.candidates) > 1:
        _log.warning(
            json.dumps(
                {
                    "event": "ledger_ambiguous_name_match",
                    "session_id": run.session_id,
                    "candidate_job_keys": list(match.candidates),
                    "action": "created_new_pasted_job",
                }
            )
        )
        return None
    if match.job_key is None or match.job_key == own:
        return None
    if cleaned and not _url_compatible(conn, match.job_key, cleaned):
        return None
    other_runs = conn.execute(
        "SELECT 1 FROM runs WHERE job_key = ? AND session_id != ?", (match.job_key, run.session_id)
    ).fetchone()
    if other_runs is None:
        _log.warning(
            json.dumps(
                {
                    "event": "ledger_run_name_match",
                    "session_id": run.session_id,
                    "job_key": match.job_key,
                }
            )
        )
        return match.job_key
    _log.warning(
        json.dumps(
            {"event": "ledger_possible_twin_job", "matched_key": match.job_key, "own_key": own}
        )
    )
    return None


def _url_compatible(conn: sqlite3.Connection, job_key: str, cleaned_url: str) -> bool:
    """True when the job has no URL yet, or already stores this cleaned URL."""
    row = conn.execute("SELECT url FROM jobs WHERE job_key = ?", (job_key,)).fetchone()
    stored = _clean_url(row[0]) if row else None
    return stored is None or stored == cleaned_url


def _run_exists(conn: sqlite3.Connection, session_id: str) -> bool:
    row = conn.execute("SELECT 1 FROM runs WHERE session_id = ?", (session_id,)).fetchone()
    return row is not None


def job_key_by_name(conn: sqlite3.Connection, company: str, title: str) -> JobNameMatch:
    """The same-name job key, plus all candidates when several jobs match."""
    rows = conn.execute(
        "SELECT job_key FROM jobs WHERE norm_text(company) = norm_text(?) "
        "AND norm_text(title) = norm_text(?)",
        (company, title),
    ).fetchall()
    matches = [row[0] for row in rows]
    return JobNameMatch(matches[0] if len(matches) == 1 else None, tuple(matches))


def _run_blobs(run: RunRecord) -> tuple[str | None, str, str, str, str]:
    return (
        _json_or_null(run.keywords),
        json.dumps(run.render_warnings),
        json.dumps(run.scores),
        json.dumps(run.uncovered_skills),
        json.dumps(run.outcome),
    )


def _run_values(run: RunRecord, key: str, blobs: tuple[str | None, str, str, str, str]) -> tuple:
    return (
        run.session_id,
        key,
        canonical_timestamp(run.timestamp),
        run.jd_text,
        blobs[0],
        run.tailored_resume_text,
        run.pdf_path,
        run.render_page_count,
        *blobs[1:],
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


def _insert_status(
    conn: sqlite3.Connection,
    *,
    job_key: str,
    status: str,
    recorded_at: str,
    note: str | None,
    source: str,
) -> bool:
    """Append a status event without committing; callers own the transaction."""
    cursor = conn.execute(
        "INSERT INTO status_events (job_key, status, recorded_at, note, source) "
        "VALUES (?, ?, ?, ?, ?) ON CONFLICT DO NOTHING",
        (job_key, status, canonical_timestamp(recorded_at), note, source),
    )
    return cursor.rowcount == 1


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
        return _insert_status(
            conn,
            job_key=job_key,
            status=status,
            recorded_at=recorded_at,
            note=note,
            source=source,
        )


class StatusUpdate(BaseModel):
    """One status to record. Name the job by job_key, or by url / company + title."""

    status: str
    recorded_at: str
    note: str | None = None
    source: str
    job_key: str | None = None
    url: str | None = None
    company: str | None = None
    title: str | None = None
    salary_range: str | None = None


def _existing_job_key(conn: sqlite3.Connection, update: StatusUpdate) -> str | None:
    """The job a status names: its job_key, a pasted job given this URL, or a name match.

    An existing URL-keyed job wins over a same-name pasted job so Applied does not attach the
    URL to the pasted row and hide the URL job's history. Otherwise a URL plus company/title
    reuses the unique same-name job when that job has no URL or already stores this URL.
    Raises AmbiguousJobMatchError when several same-name jobs exist on a name-only write.
    """
    if update.job_key:
        return update.job_key
    cleaned = _clean_url(update.url)
    company, title = _optional_text(update.company), _optional_text(update.title)
    if cleaned:
        if job_exists(conn, cleaned):
            return cleaned
        if key := _pasted_job_with_url(conn, cleaned):
            return key
        if company and title:
            return _unique_name_job(conn, company, title, cleaned)
        return None
    if not (company and title):
        return None
    return _unique_name_job(conn, company, title, cleaned_url=None)


def _unique_name_job(
    conn: sqlite3.Connection, company: str, title: str, cleaned_url: str | None
) -> str | None:
    """The one same-name job, optionally requiring its URL to be empty or cleaned_url.

    Name-only writes raise AmbiguousJobMatchError when several jobs share the name. A URL write
    with several same-name jobs returns None so a new URL-keyed row is created instead.
    """
    match = job_key_by_name(conn, company, title)
    if len(match.candidates) > 1:
        if cleaned_url is not None:
            return None
        raise AmbiguousJobMatchError(match.candidates)
    if match.job_key is None:
        return None
    if cleaned_url is not None and not _url_compatible(conn, match.job_key, cleaned_url):
        return None
    return match.job_key


def _pasted_job_with_url(conn: sqlite3.Connection, url: str) -> str | None:
    """A company + title job that was later given this URL (its key stays pasted:), if any."""
    if job_exists(conn, url):
        return None
    row = conn.execute(
        "SELECT job_key FROM jobs WHERE url = ? ORDER BY first_seen DESC LIMIT 1", (url,)
    ).fetchone()
    return row[0] if row else None


def record_status(conn: sqlite3.Connection, update: StatusUpdate) -> bool:
    """Write the job and its status event in one transaction; True if the event is new.

    With a job_key, the job must exist; URL, company, title, and salary_range only fill empty
    fields. With no URL, an existing job with the same company and title (ignoring case and
    spacing) is reused.
    Otherwise the job is created or merged from url / company + title.
    """
    with conn:
        if key := _existing_job_key(conn, update):
            cleaned_url = _clean_url(update.url)
            if update.job_key and cleaned_url:
                url_key = job_key(cleaned_url, None, None)
                target_url = conn.execute(
                    "SELECT url FROM jobs WHERE job_key = ?", (key,)
                ).fetchone()
                stored_url = _clean_url(target_url[0]) if target_url else None
                can_merge = target_url is not None and (
                    stored_url is None or stored_url == cleaned_url
                )
                if url_key != key and job_exists(conn, url_key) and can_merge:
                    conn.execute(
                        _FILL_JOB_FROM_URL_JOB, (url_key, url_key, url_key, url_key, url_key, key)
                    )
                    conn.execute(
                        "UPDATE OR IGNORE status_events SET job_key = ? WHERE job_key = ?",
                        (key, url_key),
                    )
                    # Leftovers are exact duplicates under the identity index.
                    conn.execute("DELETE FROM status_events WHERE job_key = ?", (url_key,))
                    conn.execute("UPDATE runs SET job_key = ? WHERE job_key = ?", (key, url_key))
                    conn.execute("DELETE FROM jobs WHERE job_key = ?", (url_key,))
            conn.execute(
                "UPDATE jobs SET url = COALESCE(NULLIF(url, ''), ?), "
                "company = COALESCE(NULLIF(company, ''), ?), "
                "title = COALESCE(NULLIF(title, ''), ?), "
                "salary_range = COALESCE(NULLIF(salary_range, ''), ?) "
                "WHERE job_key = ?",
                (
                    cleaned_url,
                    _optional_text(update.company),
                    _optional_text(update.title),
                    clean_salary(update.salary_range) or None,
                    key,
                ),
            )
        else:
            key = _upsert_job(
                conn,
                url=update.url,
                company=update.company,
                title=update.title,
                seen_at=update.recorded_at,
                salary_range=update.salary_range,
            )
        return _insert_status(
            conn,
            job_key=key,
            status=update.status,
            recorded_at=update.recorded_at,
            note=update.note,
            source=update.source,
        )


EXPORT_COLUMNS = [
    "Company",
    "Title",
    "URL",
    "Salary range",
    "Status",
    "Status date",
    "Notes",
    "Score before",
    "Score after",
    "Resume PDF",
]
_FORMULA_STARTS = ("=", "+", "-", "@", "\t", "\r", "\n")
# Unicode case-insensitive prefix; no LIKE, so wildcards in the prefix are literal.
_STATUS_MATCH = (
    "(:status IS NULL OR "
    "substr(norm_text(e.status), 1, length(norm_text(:status))) = norm_text(:status))"
)
_EXPORT_SQL = f"""
WITH latest_status AS (
    SELECT job_key, status, recorded_at, note,
           ROW_NUMBER() OVER (PARTITION BY job_key ORDER BY recorded_at DESC, id DESC) AS rn
    FROM status_events
), latest_run AS (
    SELECT job_key, scores, pdf_path,
           ROW_NUMBER() OVER (PARTITION BY job_key ORDER BY finalized_at DESC, rowid DESC) AS rn
    FROM runs
)
SELECT j.company, j.title, j.url, j.salary_range, s.status, s.recorded_at, s.note,
       json_extract(r.scores, '$.initial.total'), json_extract(r.scores, '$.final.total'),
       r.pdf_path
FROM jobs j
LEFT JOIN latest_status s ON s.job_key = j.job_key AND s.rn = 1
LEFT JOIN latest_run r ON r.job_key = j.job_key AND r.rn = 1
WHERE (:status IS NULL AND :since IS NULL) OR EXISTS (
    SELECT 1 FROM status_events e
    WHERE e.job_key = j.job_key
      AND {_STATUS_MATCH}
      AND (:since IS NULL OR e.recorded_at >= :since)
)
ORDER BY s.recorded_at DESC, j.job_key
"""
EVENT_COLUMNS = ["Date", "Company", "Title", "URL", "Status", "Notes", "Source"]
# An EDD-reportable event: a contact note, or an application or its confirmation.
# Exclude notes whose `|`-segments include an exact `Not reportable` marker (leading or middle).
_CONTACT_FILTER = """
  AND instr('|' || replace(ifnull(norm_text(e.note), ''), ' | ', '|') || '|',
            '|not reportable|') = 0
  AND (norm_text(e.note) LIKE 'contact method:%'
       OR norm_text(e.status) LIKE 'applied%'
       OR norm_text(e.status) LIKE 'already applied%')
"""


def _events_sql(extra: str = "") -> str:
    return f"""
SELECT e.recorded_at, j.company, j.title, j.url, e.status, e.note, e.source
FROM status_events e
JOIN jobs j ON j.job_key = e.job_key
WHERE {_STATUS_MATCH}
  AND (:since IS NULL OR e.recorded_at >= :since){extra}
ORDER BY e.recorded_at DESC, e.id DESC
"""


# True when any status event of the job proves a submission.
_EVER_APPLIED_SQL = (
    "EXISTS (SELECT 1 FROM status_events e WHERE e.job_key = j.job_key AND ("
    "norm_text(e.status) LIKE 'applied%' OR norm_text(e.status) LIKE 'already applied%' "
    "OR norm_text(e.status) LIKE 'interview%' OR norm_text(e.status) LIKE 'rejected%' "
    "OR norm_text(e.status) LIKE 'offer%' "
    # Legacy EDD work-search contacts are applications whatever the outcome (ledger_import's
    # CONTACTS_SOURCE and NOT_REPORTABLE_PREFIX; importing them here would be a cycle).
    "OR (e.source = 'contacts-import' AND e.note NOT LIKE 'Not reportable%')))"
)
_FIND_SQL = (
    "SELECT j.company, j.title, j.url, s.status, " + _EVER_APPLIED_SQL + ", "
    "s.recorded_at, j.job_key, "
    "(SELECT json_extract(r.scores, '$.initial.total') FROM runs r "
    "WHERE r.job_key = j.job_key ORDER BY r.finalized_at DESC, r.rowid DESC LIMIT 1), "
    "(SELECT json_extract(r.scores, '$.final.total') FROM runs r "
    "WHERE r.job_key = j.job_key ORDER BY r.finalized_at DESC, r.rowid DESC LIMIT 1) FROM jobs j "
    "LEFT JOIN status_events s ON s.job_key = j.job_key WHERE {where} "
    "ORDER BY {order} s.recorded_at DESC, s.id DESC LIMIT 1"
)
_BY_KEY = ("j.job_key = ?", "")
# A job first keyed by company + title keeps its pasted: key after a URL is added to it.
_BY_STORED_URL = ("j.url = ?", "j.first_seen DESC,")
_BY_NAME = (
    "norm_text(j.company) = norm_text(?) AND norm_text(j.title) = norm_text(?)",
    "j.first_seen DESC,",
)
_FIND_KEYS = [
    "company",
    "title",
    "url",
    "status",
    "ever_applied",
    "status_date",
    "job_key",
    "score_before",
    "score_after",
]
_COMPANY_JOBS_LIMIT = 20
_COMPANY_JOBS_SQL = (
    "SELECT j.job_key, j.url, j.title, s.status, s.recorded_at, " + _EVER_APPLIED_SQL + " "
    "FROM jobs j "
    "LEFT JOIN status_events s ON s.id = ("
    "SELECT e.id FROM status_events e WHERE e.job_key = j.job_key "
    "ORDER BY e.recorded_at DESC, e.id DESC LIMIT 1) "
    "WHERE norm_text(j.company) = norm_text(?) AND j.job_key IS NOT ? "
    f"ORDER BY j.first_seen DESC, j.job_key LIMIT {_COMPANY_JOBS_LIMIT}"
)


def spreadsheet_safe(row: dict) -> dict:
    """Prefix text that a spreadsheet would run as a formula with ', so postings can't inject.

    Leading spaces and non-breaking spaces are stripped before the check, so ` =1+1` is
    defused; tab/CR/LF prefixes stay as formula starts on the original value.
    """
    out = {}
    for name, value in row.items():
        if not isinstance(value, str):
            out[name] = value
            continue
        stripped = value.lstrip(" \xa0")
        out[name] = f"'{stripped}" if stripped.startswith(_FORMULA_STARTS) else value
    return out


def export_rows(
    conn: sqlite3.Connection, *, status_prefix: str | None = None, since: str | None = None
) -> list[dict]:
    """One row per job: its latest status and its latest run's scores.

    status_prefix and since match ANY status event of the job (so a job once 'Applied' still
    shows after it is 'Rejected'); the row shows the latest status. status_prefix matches the
    start of the status text (Unicode case-insensitive, wildcards taken literally; empty means no
    filter), so 'Applied' also matches 'Applied - confirmed'. since compares
    as text, so pass YYYY-MM-DD.
    """
    params = {"status": _status_prefix(status_prefix), "since": since}
    return [
        dict(zip(EXPORT_COLUMNS, row, strict=True)) for row in conn.execute(_EXPORT_SQL, params)
    ]


def export_events(
    conn: sqlite3.Connection, *, status_prefix: str | None = None, since: str | None = None
) -> list[dict]:
    """One row per status event (EVENT_COLUMNS), newest first. For an EDD contact log.

    Unlike export_rows, status_prefix and since filter the event itself, so an 'Applied' event
    keeps its own date even after the job is 'Rejected'. Same matching rules as export_rows.
    """
    return _event_rows(conn, _events_sql(), status_prefix, since)


def export_contacts(
    conn: sqlite3.Connection, *, status_prefix: str | None = None, since: str | None = None
) -> list[dict]:
    """export_events limited to EDD-reportable events.

    Keeps events whose note starts with 'Contact method:' and events whose status starts with
    'Applied' or 'Already applied' (Unicode case-insensitive), except notes starting
    'Not reportable' or 'Not reportable |' (legacy contacts the user marked non-reportable). Same
    columns and filters.
    """
    return _event_rows(conn, _events_sql(_CONTACT_FILTER), status_prefix, since)


def _event_rows(
    conn: sqlite3.Connection, sql: str, status_prefix: str | None, since: str | None
) -> list[dict]:
    params = {"status": _status_prefix(status_prefix), "since": since}
    return [dict(zip(EVENT_COLUMNS, row, strict=True)) for row in conn.execute(sql, params)]


def _status_prefix(status_prefix: str | None) -> str | None:
    """A status prefix with outer spaces trimmed, or None for no filter."""
    return (status_prefix or "").strip() or None


def job_exists(conn: sqlite3.Connection, key: str) -> bool:
    return conn.execute("SELECT 1 FROM jobs WHERE job_key = ?", (key,)).fetchone() is not None


def _find_row(conn: sqlite3.Connection, where: tuple[str, str], params: tuple) -> tuple | None:
    return conn.execute(_FIND_SQL.format(where=where[0], order=where[1]), params).fetchone()


def _key_match_kind(row: tuple | None, title: str | None) -> str:
    """'key', or 'key_title_mismatch' when a given title differs from or fills a missing one.

    One careers page can hold several postings behind #anchors that the key drops, so a key
    match with another title may be a different job: callers confirm it like a name match.
    """
    stored = _optional_text(row[_FIND_KEYS.index("title")]) if row else None
    given = _optional_text(title)
    if given and (not stored or _norm_text(stored) != _norm_text(given)):
        return "key_title_mismatch"
    return "key"


def _ambiguous_name_result(candidates: tuple[str, ...]) -> dict:
    result: dict[str, object | None] = dict(zip(_FIND_KEYS, (None,) * len(_FIND_KEYS), strict=True))
    result["ever_applied"] = False
    return {
        "found": False,
        **result,
        "matched_by": "company_title_ambiguous",
        "candidate_job_keys": list(candidates),
    }


def find_job(
    conn: sqlite3.Connection, *, url: str | None, company: str | None, title: str | None
) -> dict:
    """Is this posting already in the ledger, and what is its latest status? For dedupe.

    Looks up by URL (or company + title when there is no URL) first. A posting seen under a
    different URL is still found when company and title match, ignoring case, Unicode case, and
    spacing. Returns the stored URL, whether any status event proves submission, and the latest
    run's score totals when a run exists. A key match whose stored title differs from `title` or
    is missing reports matched_by='key_title_mismatch'. When more than one job shares the company
    and title, returns found=False with matched_by='company_title_ambiguous' and
    candidate_job_keys for the caller to disambiguate — including when a URL-less lookup would
    otherwise hit a pasted key while a URL-keyed twin exists. When nothing is found, or the match
    is weak (not 'key') or a key match whose job has no status event (a run-only job), and a
    company is given,
    company_jobs lists that company's other jobs (up to 20, newest first, the matched job left
    out) so the caller can spot a similar title or requisition id.
    """
    cleaned = _clean_url(url)
    derived = job_key(url, company, title)
    row = _find_row(conn, _BY_KEY, (derived,))
    # A pasted-key hit on a URL-less lookup can hide a same-name URL job; treat that as ambiguous.
    if row is not None and cleaned is None and company and title:
        match = job_key_by_name(conn, company, title)
        if len(match.candidates) > 1:
            return _ambiguous_name_result(match.candidates)
    matched_by = _key_match_kind(row, title) if row else None
    if row is None and cleaned:
        row = _find_row(conn, _BY_STORED_URL, (cleaned,))
        matched_by = _key_match_kind(row, title) if row else None
    if row is None and company and title:
        match = job_key_by_name(conn, company, title)
        if len(match.candidates) > 1:
            return _ambiguous_name_result(match.candidates)
        if match.job_key is not None:
            row = _find_row(conn, _BY_KEY, (match.job_key,))
            matched_by = "company_title"
    values = row or (None,) * len(_FIND_KEYS)
    result: dict[str, object | None] = dict(zip(_FIND_KEYS, values, strict=True))
    result["ever_applied"] = bool(result["ever_applied"])
    return {
        "found": row is not None,
        **result,
        "matched_by": matched_by if row else None,
        "company_jobs": _other_company_jobs(conn, company, row, matched_by),
    }


def _other_company_jobs(
    conn: sqlite3.Connection, company: str | None, row: tuple | None, matched_by: str
) -> list[dict]:
    """The company's other jobs when the match is missing, weak, or a key match with no status."""
    if not company or (row and matched_by == "key" and row[_FIND_KEYS.index("status")]):
        return []
    found_key = row[_FIND_KEYS.index("job_key")] if row else None
    keys = ("job_key", "url", "title", "status", "status_date", "ever_applied")
    return [
        {**dict(zip(keys, values, strict=True)), "ever_applied": bool(values[-1])}
        for values in conn.execute(_COMPANY_JOBS_SQL, (company, found_key))
    ]
