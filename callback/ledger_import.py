"""One-time import of old run archives, the job-hunt record CSV, and the old contact ledger.

Safe to run again: runs are keyed by session_id, status events by their full identity.
Source files are only read, never changed.
"""

from __future__ import annotations

import csv
import datetime
import json
import logging
import re
import sqlite3
from pathlib import Path
from typing import NamedTuple
from urllib.parse import urlsplit

from pydantic import BaseModel, ValidationError

from callback import ledger

logger = logging.getLogger(__name__)

CSV_SOURCE = "csv-import"
CONTACTS_SOURCE = "contacts-import"
_REQUIRED_CSV_COLUMNS = ("Company", "Title", "URL")
_US_DATE = re.compile(r"^(\d{1,2})/(\d{1,2})/(\d{4}|\d{2})$")
_TWO_DIGIT_YEAR_BASE = 2000
_TWO_DIGIT_YEAR_LIMIT = 100
_ISO_DAY = re.compile(r"^\d{4}-\d{2}-\d{2}$")
NOTE_STATUS = "Note"
NOT_REPORTABLE_PREFIX = "Not reportable"
# Extra record-CSV columns kept in the event note: (note label, accepted header names).
_NOTE_COLUMNS = (
    ("Score before", ("Resume score before tailoring",)),
    ("Score after", ("Resume score after tailoring",)),
    ("Resume", ("Link to resume used", "Link resume used")),
    ("Cover letter", ("Link to cover letter used", "Link cover letter used")),
)
_OLDEST = datetime.datetime.min.replace(tzinfo=datetime.UTC)


class ImportReport(BaseModel):
    """Counts: imported runs or rows, new job rows, new status events, and skipped labels."""

    imported: int = 0
    skipped: list[str] = []

    jobs: int = 0
    events: int = 0


def _info(event: str, **fields: object) -> None:
    logger.info(json.dumps({"event": event, **fields}))


def _url_or_none(value: str | None) -> str | None:
    """The stripped value if it is an http(s) URL, else None."""
    text = (value or "").strip()
    try:
        parts = urlsplit(text)
    except ValueError:
        return None
    hostname = parts.hostname
    if parts.scheme.lower() not in {"http", "https"} or not hostname:
        return None
    return text if not any(character.isspace() for character in hostname) else None


def _iso_date(text: str | None) -> str | None:
    """YYYY-MM-DD, a full ISO date-time (date kept), M/D/YYYY or M/D/YY; anything else None."""
    value = (text or "").strip()
    iso = _full_iso_date(value)
    if iso:
        return iso
    match = _US_DATE.match(value)
    if not match:
        return None
    month, day, year = (int(g) for g in match.groups())
    if year < _TWO_DIGIT_YEAR_LIMIT:
        year += _TWO_DIGIT_YEAR_BASE
    try:
        return datetime.date(year, month, day).isoformat()
    except ValueError:
        return None


def _full_iso_date(value: str) -> str | None:
    """The date of a value that is entirely ISO; trailing junk makes it None."""
    try:
        if _ISO_DAY.match(value):
            return datetime.date.fromisoformat(value).isoformat()
        return datetime.datetime.fromisoformat(value).date().isoformat()
    except ValueError:
        return None  # not ISO; the caller tries the US format


def _warn(event: str, **fields: object) -> None:
    logger.warning(json.dumps({"event": event, **fields}))


def _skip(report: ImportReport, label: str, reason: str) -> None:
    report.skipped.append(label)
    _warn("ledger_import_skip", item=label, reason=reason)


class _Archive(NamedTuple):
    label: str
    path: Path
    run: ledger.RunRecord
    root: Path


def _find_pdf(archive_dir: Path, name: str) -> list[Path]:
    # Exact name compare, not a glob: names can hold [ ] * ? characters.
    return sorted(p for p in archive_dir.rglob("*") if p.is_file() and p.name == name)


def _pdf_candidates(archive: _Archive, name: str) -> list[Path]:
    """The PDF beside the archive JSON when there is one, else every match under its root."""
    sibling = archive.path.parent / name
    if sibling.is_file():
        return [sibling]
    return _find_pdf(archive.root, name)


def _relink_pdf(archive: _Archive) -> ledger.RunRecord:
    """Point a run at a PDF found near its archive when its recorded path is gone."""
    run = archive.run
    if not run.pdf_path or Path(run.pdf_path).exists():
        return run
    name = Path(run.pdf_path).name
    matches = _pdf_candidates(archive, name) if name else []
    if len(matches) > 1:
        _warn(
            "ledger_import_pdf_ambiguous",
            session_id=run.session_id,
            pdf_path=run.pdf_path,
            candidates=[str(m) for m in matches],
        )
    elif not matches:
        _warn("ledger_import_pdf_missing", session_id=run.session_id, pdf_path=run.pdf_path)
    else:
        found = matches[0].resolve()
        _warn(
            "ledger_import_pdf_relinked",
            session_id=run.session_id,
            old=run.pdf_path,
            new=str(found),
        )
        return run.model_copy(update={"pdf_path": str(found)})
    return run


def _read_archives(archive_dir: Path, report: ImportReport, *, qualify: bool) -> list[_Archive]:
    """Every readable archive in path order; unreadable ones are skipped.

    With several roots the label is `<root>/<relative path>`, so equal names stay distinct.
    """
    runs: list[_Archive] = []
    for path in sorted(archive_dir.rglob("*.json")):
        relative = str(path.relative_to(archive_dir))
        label = f"{archive_dir}/{relative}" if qualify else relative
        try:
            run = ledger.RunRecord.model_validate_json(path.read_text("utf-8"))
        except (OSError, UnicodeDecodeError, ValidationError) as exc:
            _skip(report, label, str(exc).splitlines()[0])
            continue
        if _run_time(run) is None:
            _skip(report, label, "timestamp is not ISO 8601")
            continue
        if not run.session_id.strip():
            _skip(report, label, "session_id is blank")
            continue
        if path.stem != run.session_id:
            _skip(report, label, "filename does not match session_id")
            continue
        runs.append(_Archive(label, path, run, archive_dir))
    return runs


def _run_time(run: ledger.RunRecord) -> datetime.datetime | None:
    """A valid archive timestamp, normalized to UTC when it omitted an offset."""
    try:
        moment = datetime.datetime.fromisoformat(run.timestamp)
    except ValueError:
        return None
    return moment if moment.tzinfo else moment.replace(tzinfo=datetime.UTC)


def _newest_per_session(runs: list[_Archive]) -> list[_Archive]:
    """One copy per session_id: the newest timestamp wins, ties go to the first path."""
    groups: dict[str, list[_Archive]] = {}
    for item in runs:
        groups.setdefault(item.run.session_id, []).append(item)
    kept = []
    for session_id, copies in groups.items():
        newest = max(copies, key=lambda item: _run_time(item.run) or _OLDEST)
        for dropped in (c for c in copies if c.path != newest.path):
            _warn(
                "ledger_import_duplicate_session",
                session_id=session_id,
                kept=newest.label,
                dropped=dropped.label,
            )
        kept.append(newest)
    return kept


def import_archives(conn: sqlite3.Connection, roots: Path | list[Path]) -> ImportReport:
    """Import the newest run for every session across all archive roots."""
    archive_roots = [roots] if isinstance(roots, Path) else roots
    for archive_dir in archive_roots:
        if not archive_dir.is_dir():
            raise ValueError(f"cannot read archive folder {archive_dir}: not a folder")
    report = ImportReport()
    qualify = len(archive_roots) > 1
    candidates = [
        candidate
        for archive_dir in archive_roots
        for candidate in _read_archives(archive_dir, report, qualify=qualify)
    ]
    for archive in _newest_per_session(candidates):
        _import_archive(conn, archive, report)
    return report


def _import_archive(conn: sqlite3.Connection, archive: _Archive, report: ImportReport) -> None:
    run = archive.run.model_copy(update={"jd_url": _url_or_none(archive.run.jd_url)})
    key = ledger.job_key(run.jd_url, run.company, run.title, run.jd_text)
    job_exists = _job_exists(conn, key)
    relinked = _relink_pdf(archive._replace(run=run))
    if not ledger.record_imported_run_if_absent(conn, relinked):
        _info("ledger_import_run_exists", session_id=run.session_id, file=archive.label)
        report.skipped.append(archive.label)
        return
    report.jobs += int(not job_exists)
    report.imported += 1


def _cell(row: dict, column: str) -> str | None:
    return (row.get(column) or "").strip() or None


def _first_cell(row: dict, columns: tuple[str, ...]) -> str | None:
    return next((v for c in columns if (v := _cell(row, c))), None)


def _extra_note_parts(row: dict) -> list[str]:
    """Scores and resume/cover-letter links, which have no column of their own in the ledger."""
    found = ((label, _first_cell(row, columns)) for label, columns in _NOTE_COLUMNS)
    return [f"{label}: {value}" for label, value in found if value]


def _note(row: dict, bad_url: str | None) -> str | None:
    email_date = _cell(row, "Email Date")
    parts = [
        _cell(row, "Notes"),
        f"Email date: {email_date}" if email_date else None,
        f"URL: {bad_url}" if bad_url else None,
        *_extra_note_parts(row),
    ]
    return " | ".join(p for p in parts if p) or None


def _event_status(row: dict, bad_url: str | None) -> str | None:
    """The row's Status; a row with only notes, scores, links or a URL descriptor is a `Note`."""
    status = _cell(row, "Status")
    if status:
        return status
    if _cell(row, "Notes") or _extra_note_parts(row) or bad_url:
        return NOTE_STATUS
    return None


def _undated_reason(bad_url: str | None) -> str:
    reason = "status or note has no valid Recorded Date or Email Date"
    return f"{reason}; URL descriptor {bad_url!r} not kept" if bad_url else reason


def _import_row(conn: sqlite3.Connection, row: dict, label: str, report: ImportReport) -> None:
    raw_url = _cell(row, "URL")
    url = _url_or_none(raw_url)
    company, title = _cell(row, "Company"), _cell(row, "Title")
    if not (url or company or title):
        _skip(report, label, "row has no URL, company, or title")
        return
    recorded_at = _iso_date(_cell(row, "Recorded Date")) or _iso_date(_cell(row, "Email Date"))
    key = _import_job(
        conn, report, label, (url, company, title), recorded_at or "", _cell(row, "Salary range")
    )
    bad_url = None if url else raw_url
    note = _with_salary_note(conn, key, _cell(row, "Salary range"), _note(row, bad_url))
    status = _event_status(row, bad_url)
    if not status:
        return
    if not recorded_at:
        _skip(report, label, _undated_reason(bad_url))
        return
    added = ledger.add_status(
        conn,
        job_key=key,
        status=status,
        recorded_at=recorded_at,
        note=note,
        source=CSV_SOURCE,
    )
    report.imported += int(added)
    report.events += int(added)


def _read_csv_rows(csv_path: Path) -> list[tuple[int, dict]]:
    """Rows with the line each one ends on. utf-8-sig drops the BOM spreadsheets add."""
    try:
        with csv_path.open(newline="", encoding="utf-8-sig") as fh:
            reader = csv.DictReader(fh)
            missing = [c for c in _REQUIRED_CSV_COLUMNS if c not in (reader.fieldnames or [])]
            if missing:
                raise ValueError(f"cannot read record CSV {csv_path}: missing columns {missing}")
            return [(reader.line_num, row) for row in reader]
    except (OSError, UnicodeDecodeError, csv.Error) as exc:
        raise ValueError(f"cannot read record CSV {csv_path}: {exc}") from exc


def import_record_csv(conn: sqlite3.Connection, csv_path: Path) -> ImportReport:
    report = ImportReport()
    for line_no, row in _read_csv_rows(csv_path):
        _import_row(conn, row, f"line {line_no}", report)
    return report


_METADATA_TABLE = "job_search_metadata"
_SALARY_KEY = "SalaryRange"
_URL_KEYS = ("SourceURL", "JobURL", "ApplicationURL")


def _read_contact_rows(db_path: Path) -> tuple[list[sqlite3.Row], dict[int, dict[str, str]]]:
    """Every entry plus its metadata (empty when an old DB has no metadata table)."""
    try:
        source = sqlite3.connect(f"{db_path.resolve().as_uri()}?mode=ro", uri=True)
    except sqlite3.Error as exc:
        raise ValueError(f"cannot read contact ledger {db_path}: {exc}") from exc
    try:
        source.row_factory = sqlite3.Row
        rows = source.execute("SELECT * FROM job_search_entries ORDER BY id").fetchall()
        return rows, _read_metadata(source, db_path)
    except sqlite3.Error as exc:
        raise ValueError(f"cannot read contact ledger {db_path}: {exc}") from exc
    finally:
        source.close()


def _read_metadata(source: sqlite3.Connection, db_path: Path) -> dict[int, dict[str, str]]:
    has_table = source.execute(
        "SELECT 1 FROM sqlite_master WHERE type = 'table' AND name = ?", (_METADATA_TABLE,)
    ).fetchone()
    if not has_table:
        _info("ledger_import_no_metadata_table", path=str(db_path))
        return {}
    metadata: dict[int, dict[str, str]] = {}
    for entry_id, key, value in source.execute(
        f"SELECT entry_id, key, value FROM {_METADATA_TABLE} ORDER BY entry_id, key"
    ):
        if _text(value):
            metadata.setdefault(entry_id, {})[key] = _text(value)
    return metadata


def _text(value: object) -> str:
    return str(value).strip() if value is not None else ""


def _is_reportable(row: sqlite3.Row) -> bool:
    """A contact counts toward reporting when `reportable` is 1."""
    return "reportable" not in row.keys() or row["reportable"] == 1  # noqa: SIM118


def _contact_prefix(row: sqlite3.Row) -> str:
    contact_type = _text(row["contact_type"])
    if _is_reportable(row):
        return f"Contact method: {contact_type}" if contact_type else ""
    parts = [NOT_REPORTABLE_PREFIX, f"Contact: {contact_type}" if contact_type else ""]
    return " | ".join(part for part in parts if part)


def _contact_note(row: sqlite3.Row, url: str | None, extras: dict[str, str]) -> str | None:
    detail = _text(row["contact_detail"])
    person = _text(row["person_contacted"])
    parts = [
        _contact_prefix(row),
        detail if detail != url else "",
        f"Person: {person}" if person else "",
        _text(row["notes"]),
        *(f"{key}: {extras[key]}" for key in sorted(extras) if key != _SALARY_KEY),
    ]
    return " | ".join(p for p in parts if p) or None


def _contact_url(row: sqlite3.Row, extras: dict[str, str]) -> str | None:
    """The first usable posting URL from metadata, else the contact detail when it is a URL.

    A contact detail can be a recruiter profile or a thread, so an explicit job URL wins; the
    detail is still kept in the note.
    """
    candidates = (_url_or_none(extras.get(key)) for key in _URL_KEYS)
    return next((c for c in candidates if c), None) or _url_or_none(_text(row["contact_detail"]))


def _import_contact(
    conn: sqlite3.Connection, row: sqlite3.Row, extras: dict[str, str], report: ImportReport
) -> None:
    label = f"entry {row['id']}"
    date, outcome = _iso_date(_text(row["date"])), _text(row["outcome"])
    if not date or not outcome:
        _skip(report, label, "missing outcome or missing/invalid date")
        return
    url = _contact_url(row, extras)
    company, title = _text(row["employer_name"]) or None, _text(row["type_of_work"]) or None
    if not (url or company or title):
        _skip(report, label, "row has no URL, employer, or work type")
        return
    salary = extras.get(_SALARY_KEY)
    key = _import_job(conn, report, label, (url, company, title), date, salary)
    note = _with_salary_note(conn, key, salary, _contact_note(row, url, extras))
    added = ledger.add_status(
        conn,
        job_key=key,
        status=outcome,
        recorded_at=date,
        note=note,
        source=CONTACTS_SOURCE,
    )
    report.imported += int(added)
    report.events += int(added)


def _with_salary_note(
    conn: sqlite3.Connection, key: str, salary_range: str | None, note: str | None
) -> str | None:
    """Add the row's salary range to its note when the job kept a different one.

    The job keeps the first range it stored, so a later source's different range would vanish.
    """
    cleaned = ledger.clean_salary(salary_range)
    stored = conn.execute("SELECT salary_range FROM jobs WHERE job_key = ?", (key,)).fetchone()
    if not cleaned or not stored or not stored[0] or stored[0] == cleaned:
        return note
    return " | ".join(p for p in (note, f"Salary range: {cleaned}") if p)


def _import_job(
    conn: sqlite3.Connection,
    report: ImportReport,
    label: str,
    posting: tuple[str | None, str | None, str | None],
    seen_at: str,
    salary_range: str | None,
) -> str:
    """The job an imported row belongs to: the one existing job with the same company and
    title when the row has no URL, else a new or merged job."""
    url, company, title = posting
    matched = _name_match(conn, url, company, title)
    if matched:
        with conn:
            conn.execute(
                "UPDATE jobs SET salary_range = COALESCE(NULLIF(salary_range, ''), ?),"
                " url = COALESCE(NULLIF(url, ''), ?) WHERE job_key = ?",
                (
                    ledger.clean_salary(salary_range),
                    ledger.normalize_url(url) if url else None,
                    matched,
                ),
            )
        _warn("ledger_import_name_match", label=label, job_key=matched)
        return matched
    return _upsert_import_job(
        conn,
        report=report,
        url=url,
        company=company,
        title=title,
        seen_at=seen_at,
        salary_range=salary_range,
    )


def _name_match(
    conn: sqlite3.Connection, url: str | None, company: str | None, title: str | None
) -> str | None:
    """The one same-name job a row joins: any job for a URL-less row, else a URL-less job
    or one already promoted to the row's URL when no job exists yet for that URL."""
    if not (company and title):
        return None
    if not url:
        return ledger.job_key_by_name(conn, company, title).job_key
    if _job_exists(conn, ledger.job_key(url, None, None)):
        return None
    matched = ledger.job_key_by_name(conn, company, title).job_key
    if matched is None:
        return None
    row = conn.execute("SELECT url FROM jobs WHERE job_key = ?", (matched,)).fetchone()
    normalized_url = ledger.normalize_url(url)
    return matched if row and (not row[0] or row[0] == normalized_url) else None


def _upsert_import_job(
    conn: sqlite3.Connection,
    *,
    report: ImportReport,
    url: str | None,
    company: str | None,
    title: str | None,
    seen_at: str,
    salary_range: str | None = None,
) -> str:
    key = ledger.job_key(url, company, title)
    existed = _job_exists(conn, key)
    ledger.upsert_job(
        conn,
        url=url,
        company=company,
        title=title,
        seen_at=seen_at,
        salary_range=salary_range,
    )
    report.jobs += int(not existed)
    return key


def _job_exists(conn: sqlite3.Connection, key: str) -> bool:
    row = conn.execute("SELECT 1 FROM jobs WHERE job_key = ?", (key,)).fetchone()
    return row is not None


def import_contact_ledger(conn: sqlite3.Connection, db_path: Path) -> ImportReport:
    report = ImportReport()
    rows, metadata = _read_contact_rows(db_path)
    column_names = rows[0].keys() if rows else ()
    if rows and "reportable" not in column_names:
        _warn(
            "ledger_import_no_reportable_column",
            path=str(db_path),
            action="every contact is treated as reportable",
        )
    for row in rows:
        _import_contact(conn, row, metadata.get(row["id"], {}), report)
    return report
