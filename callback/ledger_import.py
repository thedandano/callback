"""One-time import of old run archives, the job-hunt record CSV, and the old contact ledger.

Safe to run again: runs are keyed by session_id, status events by (job, status, date).
Source files are only read, never changed.
"""

from __future__ import annotations

import csv
import json
import logging
import sqlite3
from pathlib import Path

from pydantic import BaseModel, ValidationError

from callback import ledger

logger = logging.getLogger(__name__)

CSV_SOURCE = "csv-import"
CONTACTS_SOURCE = "contacts-import"
_FIRST_DATA_LINE = 2  # line 1 is the header
_HTTP_PREFIXES = ("http://", "https://")


class ImportReport(BaseModel):
    imported: int = 0
    skipped: list[str] = []


def _warn(event: str, **fields: object) -> None:
    logger.warning(json.dumps({"event": event, **fields}))


def _skip(report: ImportReport, label: str, reason: str) -> None:
    report.skipped.append(label)
    _warn("ledger_import_skip", item=label, reason=reason)


def _run_exists(conn: sqlite3.Connection, session_id: str) -> bool:
    row = conn.execute("SELECT 1 FROM runs WHERE session_id = ?", (session_id,)).fetchone()
    return row is not None


def _relink_pdf(run: ledger.RunRecord, archive_dir: Path) -> ledger.RunRecord:
    """Point a run at a PDF found under archive_dir when its recorded path is gone."""
    if not run.pdf_path or Path(run.pdf_path).exists():
        return run
    found = next(archive_dir.rglob(Path(run.pdf_path).name), None)
    if found is None:
        _warn("ledger_import_pdf_missing", session_id=run.session_id, pdf_path=run.pdf_path)
        return run
    _warn(
        "ledger_import_pdf_relinked",
        session_id=run.session_id,
        old=run.pdf_path,
        new=str(found),
    )
    return run.model_copy(update={"pdf_path": str(found)})


def import_archives(conn: sqlite3.Connection, archive_dir: Path) -> ImportReport:
    if not archive_dir.is_dir():
        raise ValueError(f"cannot read archive folder {archive_dir}: not a folder")
    report = ImportReport()
    for path in sorted(archive_dir.rglob("*.json")):
        label = str(path.relative_to(archive_dir))
        try:
            run = ledger.RunRecord.model_validate_json(path.read_text(encoding="utf-8"))
        except (OSError, UnicodeDecodeError, ValidationError) as exc:
            _skip(report, label, str(exc).splitlines()[0])
            continue
        if _run_exists(conn, run.session_id):
            continue  # never overwrite a run the ledger already holds
        ledger.record_run(conn, _relink_pdf(run, archive_dir))
        report.imported += 1
    return report


def _cell(row: dict, column: str) -> str | None:
    return (row.get(column) or "").strip() or None


def _note(row: dict) -> str | None:
    parts = [_cell(row, "Notes"), f"Email date: {d}" if (d := _cell(row, "Email Date")) else None]
    return " | ".join(p for p in parts if p) or None


def _import_row(conn: sqlite3.Connection, row: dict, label: str, report: ImportReport) -> None:
    recorded_at = _cell(row, "Recorded Date") or _cell(row, "Email Date")
    key = ledger.upsert_job(
        conn,
        url=_cell(row, "URL"),
        company=_cell(row, "Company"),
        title=_cell(row, "Title"),
        seen_at=recorded_at or "",
        salary_range=_cell(row, "Salary range"),
    )
    status = _cell(row, "Status")
    if not status:
        return
    if not recorded_at:
        _skip(report, label, "status has no Recorded Date or Email Date")
        return
    added = ledger.add_status(
        conn,
        job_key=key,
        status=status,
        recorded_at=recorded_at,
        note=_note(row),
        source=CSV_SOURCE,
    )
    report.imported += int(added)


def _read_csv_rows(csv_path: Path) -> list[dict]:
    # utf-8-sig: spreadsheet exports start with a BOM that would corrupt the first column name.
    try:
        with csv_path.open(newline="", encoding="utf-8-sig") as fh:
            return list(csv.DictReader(fh))
    except (OSError, UnicodeDecodeError, csv.Error) as exc:
        raise ValueError(f"cannot read record CSV {csv_path}: {exc}") from exc


def import_record_csv(conn: sqlite3.Connection, csv_path: Path) -> ImportReport:
    report = ImportReport()
    rows = _read_csv_rows(csv_path)
    for line_no, row in enumerate(rows, start=_FIRST_DATA_LINE):
        _import_row(conn, row, f"line {line_no}", report)
    return report


_CONTACT_QUERY = (
    "SELECT id, date, employer_name, type_of_work, contact_type, outcome, "
    "contact_detail, person_contacted, notes FROM job_search_entries ORDER BY id"
)


def _read_contact_rows(db_path: Path) -> list[sqlite3.Row]:
    try:
        source = sqlite3.connect(f"file:{db_path}?mode=ro", uri=True)
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
    date, outcome = _text(row["date"]), _text(row["outcome"])
    if not date or not outcome:
        _skip(report, f"entry {row['id']}", "missing date or outcome")
        return
    detail = _text(row["contact_detail"])
    url = detail if detail.startswith(_HTTP_PREFIXES) else None
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
