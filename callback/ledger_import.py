"""One-time import of old run archives, the job-hunt record CSV, and the old contact ledger.

Safe to run again: runs are keyed by session_id, status events by (job, status, date).
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

from pydantic import BaseModel, ValidationError

from callback import ledger

logger = logging.getLogger(__name__)

CSV_SOURCE = "csv-import"
CONTACTS_SOURCE = "contacts-import"
_REQUIRED_CSV_COLUMNS = ("Company", "Title", "URL")
_US_DATE = re.compile(r"^(\d{1,2})/(\d{1,2})/(\d{4}|\d{2})$")
_TWO_DIGIT_YEAR_BASE = 2000
_TWO_DIGIT_YEAR_LIMIT = 100
_ISO_DATE_LENGTH = 10
_HTTP_PREFIXES = ("http://", "https://")
NOTE_STATUS = "Note"
# Extra record-CSV columns kept in the event note: (note label, accepted header names).
_NOTE_COLUMNS = (
    ("Score before", ("Resume score before tailoring",)),
    ("Score after", ("Resume score after tailoring",)),
    ("Resume", ("Link to resume used", "Link resume used")),
    ("Cover letter", ("Link to cover letter used", "Link cover letter used")),
)
_OLDEST = datetime.datetime.min.replace(tzinfo=datetime.UTC)


class ImportReport(BaseModel):
    imported: int = 0
    skipped: list[str] = []


def _info(event: str, **fields: object) -> None:
    logger.info(json.dumps({"event": event, **fields}))


def _url_or_none(value: str | None) -> str | None:
    """The stripped value if it is an http(s) URL, else None."""
    text = (value or "").strip()
    return text if text.lower().startswith(_HTTP_PREFIXES) else None


def _iso_date(text: str | None) -> str | None:
    """YYYY-MM-DD (any time part dropped); M/D/YYYY and M/D/YY converted; anything else None."""
    value = (text or "").strip()
    try:
        datetime.date.fromisoformat(value[:_ISO_DATE_LENGTH])
    except ValueError:
        pass  # not ISO; try the US format below
    else:
        return value[:_ISO_DATE_LENGTH]
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


def _warn(event: str, **fields: object) -> None:
    logger.warning(json.dumps({"event": event, **fields}))


def _skip(report: ImportReport, label: str, reason: str) -> None:
    report.skipped.append(label)
    _warn("ledger_import_skip", item=label, reason=reason)


def _run_exists(conn: sqlite3.Connection, session_id: str) -> bool:
    row = conn.execute("SELECT 1 FROM runs WHERE session_id = ?", (session_id,)).fetchone()
    return row is not None


def _find_pdf(archive_dir: Path, name: str) -> list[Path]:
    # Exact name compare, not a glob: names can hold [ ] * ? characters.
    return sorted(p for p in archive_dir.rglob("*") if p.is_file() and p.name == name)


def _relink_pdf(run: ledger.RunRecord, archive_dir: Path) -> ledger.RunRecord:
    """Point a run at a PDF found under archive_dir when its recorded path is gone."""
    if not run.pdf_path or Path(run.pdf_path).exists():
        return run
    name = Path(run.pdf_path).name
    matches = _find_pdf(archive_dir, name) if name else []
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
        _warn(
            "ledger_import_pdf_relinked",
            session_id=run.session_id,
            old=run.pdf_path,
            new=str(matches[0]),
        )
        return run.model_copy(update={"pdf_path": str(matches[0])})
    return run


def _read_archives(archive_dir: Path, report: ImportReport) -> list[tuple[str, ledger.RunRecord]]:
    """Every readable archive as (label, run), in path order; unreadable ones are skipped."""
    runs = []
    for path in sorted(archive_dir.rglob("*.json")):
        label = str(path.relative_to(archive_dir))
        try:
            runs.append((label, ledger.RunRecord.model_validate_json(path.read_text("utf-8"))))
        except (OSError, UnicodeDecodeError, ValidationError) as exc:
            _skip(report, label, str(exc).splitlines()[0])
    return runs


def _run_time(label: str, run: ledger.RunRecord) -> datetime.datetime:
    """The run's timestamp for picking the newest copy; an unreadable one sorts oldest."""
    try:
        moment = datetime.datetime.fromisoformat(run.timestamp)
    except ValueError:
        _warn("ledger_import_bad_timestamp", file=label, timestamp=run.timestamp)
        return _OLDEST
    return moment if moment.tzinfo else moment.replace(tzinfo=datetime.UTC)


def _newest_per_session(
    runs: list[tuple[str, ledger.RunRecord]],
) -> list[tuple[str, ledger.RunRecord]]:
    """One copy per session_id: the newest timestamp wins, ties go to the first path."""
    groups: dict[str, list[tuple[str, ledger.RunRecord]]] = {}
    for item in runs:
        groups.setdefault(item[1].session_id, []).append(item)
    kept = []
    for session_id, copies in groups.items():
        newest = max(copies, key=lambda item: _run_time(*item))
        for label, _ in copies:
            if label != newest[0]:
                _warn(
                    "ledger_import_duplicate_session",
                    session_id=session_id,
                    kept=newest[0],
                    dropped=label,
                )
        kept.append(newest)
    return kept


def import_archives(conn: sqlite3.Connection, archive_dir: Path) -> ImportReport:
    if not archive_dir.is_dir():
        raise ValueError(f"cannot read archive folder {archive_dir}: not a folder")
    report = ImportReport()
    for label, run in _newest_per_session(_read_archives(archive_dir, report)):
        if _run_exists(conn, run.session_id):
            # Expected on a re-run; never overwrite a run the ledger already holds.
            _info("ledger_import_run_exists", session_id=run.session_id, file=label)
            continue
        run = run.model_copy(update={"jd_url": _url_or_none(run.jd_url)})
        ledger.record_run(conn, _relink_pdf(run, archive_dir))
        report.imported += 1
    return report


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


def _event_status(row: dict) -> str | None:
    """The row's Status; a row with only notes, scores or links becomes a `Note` event."""
    status = _cell(row, "Status")
    if status:
        return status
    if _cell(row, "Notes") or _extra_note_parts(row):
        return NOTE_STATUS
    return None


def _import_row(conn: sqlite3.Connection, row: dict, label: str, report: ImportReport) -> None:
    raw_url = _cell(row, "URL")
    url = _url_or_none(raw_url)
    company, title = _cell(row, "Company"), _cell(row, "Title")
    if not (url or company or title):
        _skip(report, label, "row has no URL, company, or title")
        return
    recorded_at = _iso_date(_cell(row, "Recorded Date")) or _iso_date(_cell(row, "Email Date"))
    key = ledger.upsert_job(
        conn,
        url=url,
        company=company,
        title=title,
        seen_at=recorded_at or "",
        salary_range=_cell(row, "Salary range"),
    )
    status = _event_status(row)
    if not status:
        return
    if not recorded_at:
        _skip(report, label, "status or note has no valid Recorded Date or Email Date")
        return
    bad_url = None if url else raw_url
    added = ledger.add_status(
        conn,
        job_key=key,
        status=status,
        recorded_at=recorded_at,
        note=_note(row, bad_url),
        source=CSV_SOURCE,
    )
    report.imported += int(added)


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


_CONTACT_QUERY = (
    "SELECT id, date, employer_name, type_of_work, contact_type, outcome, "
    "contact_detail, person_contacted, notes FROM job_search_entries ORDER BY id"
)


def _read_contact_rows(db_path: Path) -> list[sqlite3.Row]:
    try:
        source = sqlite3.connect(f"{db_path.resolve().as_uri()}?mode=ro", uri=True)
    except sqlite3.Error as exc:
        raise ValueError(f"cannot read contact ledger {db_path}: {exc}") from exc
    try:
        source.row_factory = sqlite3.Row
        return source.execute(_CONTACT_QUERY).fetchall()
    except sqlite3.Error as exc:
        raise ValueError(f"cannot read contact ledger {db_path}: {exc}") from exc
    finally:
        source.close()


def _text(value: object) -> str:
    return str(value).strip() if value is not None else ""


def _contact_note(row: sqlite3.Row, url: str | None) -> str | None:
    detail = _text(row["contact_detail"])
    person = _text(row["person_contacted"])
    contact_type = _text(row["contact_type"])
    parts = [
        f"Contact: {contact_type}" if contact_type else "",
        detail if detail != url else "",
        f"Person: {person}" if person else "",
        _text(row["notes"]),
    ]
    return " | ".join(p for p in parts if p) or None


def _import_contact(conn: sqlite3.Connection, row: sqlite3.Row, report: ImportReport) -> None:
    date, outcome = _iso_date(_text(row["date"])), _text(row["outcome"])
    if not date or not outcome:
        _skip(report, f"entry {row['id']}", "missing outcome or missing/invalid date")
        return
    url = _url_or_none(_text(row["contact_detail"]))
    key = ledger.upsert_job(
        conn,
        url=url,
        company=_text(row["employer_name"]) or None,
        title=_text(row["type_of_work"]) or None,
        seen_at=date,
    )
    added = ledger.add_status(
        conn,
        job_key=key,
        status=outcome,
        recorded_at=date,
        note=_contact_note(row, url),
        source=CONTACTS_SOURCE,
    )
    report.imported += int(added)


def import_contact_ledger(conn: sqlite3.Connection, db_path: Path) -> ImportReport:
    report = ImportReport()
    for row in _read_contact_rows(db_path):
        _import_contact(conn, row, report)
    return report
