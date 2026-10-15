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
    url = COALESCE(jobs.url, excluded.url),
    company = COALESCE(jobs.company, excluded.company),
    title = COALESCE(jobs.title, excluded.title),
    salary_range = COALESCE(jobs.salary_range, excluded.salary_range),
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


def canonical_timestamp(value: str) -> str:
    """UTC ISO form of a timestamp, so text and time order agree.

    A time with no offset is read as UTC. Plain `YYYY-MM-DD` dates and blanks come back stripped;
    text that is not ISO comes back as given and logs a warning.
    """
    stripped = value.strip()
    try:
        if not stripped or (_PLAIN_DATE.fullmatch(stripped) and date.fromisoformat(stripped)):
            return stripped
        parsed = datetime.fromisoformat(stripped)
    except ValueError:
        _log.warning(json.dumps({"event": "ledger_timestamp_unparsed", "value": value}))
        return value
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=UTC)
    return parsed.astimezone(UTC).isoformat()


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
    """
    company = (company or "").strip() or None
    title = (title or "").strip() or None
    key = key or job_key(url, company, title, jd_text)
    conn.execute(
        _UPSERT_JOB,
        (
            key,
            _clean_url(url),
            company,
            title,
            clean_salary(salary_range),
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
        key = _upsert_run_job(conn, run)
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

    A session already in `runs` stays on its job (a retry). A new run with no URL may join the
    one same-name job that has no runs.
    """
    existing = conn.execute(
        "SELECT job_key FROM runs WHERE session_id = ?", (run.session_id,)
    ).fetchone()
    return _upsert_job(
        conn,
        url=run.jd_url,
        company=run.company,
        title=run.title,
        seen_at=run.timestamp,
        salary_range=_salary_range(run.keywords),
        jd_text=run.jd_text,
        key=existing[0] if existing else _same_name_job_key(conn, run),
    )


def _same_name_job_key(conn: sqlite3.Connection, run: RunRecord) -> str | None:
    """Key of the one job a URL-less run belongs to (the scan-then-tailor case), else None.

    Joins only when the company and title match exactly one job and that job has no other
    runs. A job that already has runs may be a different posting, so the run keeps its own
    pasted key and the possible twin is logged.
    """
    if _clean_url(run.jd_url) or not (run.company and run.title):
        return None
    matched = job_key_by_name(conn, run.company, run.title)
    own = job_key(None, run.company, run.title, run.jd_text)
    if matched is None or matched == own:
        return None
    other_runs = conn.execute(
        "SELECT 1 FROM runs WHERE job_key = ? AND session_id != ?", (matched, run.session_id)
    ).fetchone()
    if other_runs is None:
        return matched
    _log.warning(
        json.dumps({"event": "ledger_possible_twin_job", "matched_key": matched, "own_key": own})
    )
    return None


def _run_exists(conn: sqlite3.Connection, session_id: str) -> bool:
    row = conn.execute("SELECT 1 FROM runs WHERE session_id = ?", (session_id,)).fetchone()
    return row is not None


def _name_form(text: str) -> str:
    return " ".join(text.split()).casefold()


def job_key_by_name(conn: sqlite3.Connection, company: str, title: str) -> str | None:
    """The one job whose company and title match ignoring case and spacing, else None.

    None when nothing matches or several jobs match; the caller then keeps its own key.
    """
    wanted = (_name_form(company), _name_form(title))
    rows = conn.execute(
        "SELECT job_key, company, title FROM jobs WHERE company IS NOT NULL AND title IS NOT NULL"
    )
    matches = [key for key, name, role in rows if (_name_form(name), _name_form(role)) == wanted]
    return matches[0] if len(matches) == 1 else None


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
        run.timestamp,
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
            "INSERT INTO status_events (job_key, status, recorded_at, note, source) "
            "VALUES (?, ?, ?, ?, ?) ON CONFLICT DO NOTHING",
            (job_key, status, canonical_timestamp(recorded_at), note, source),
        )
    return cursor.rowcount == 1
