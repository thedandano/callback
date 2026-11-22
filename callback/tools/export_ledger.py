"""MCP tool `export_ledger`."""

import sqlite3
from contextlib import closing
from pathlib import Path

from callback.config.logging import log
from callback.models.envelope import err, ok
from callback.repositories import ledger
from callback.repositories.atomic import write_text_atomic
from callback.services.ledger_csv import csv_text
from callback.tools.ledger_inputs import date_error, ledger_error

_EXPORT_MODES = {
    "jobs": (ledger.export_rows, ledger.EXPORT_COLUMNS),
    "events": (ledger.export_events, ledger.EVENT_COLUMNS),
    "contacts": (ledger.export_contacts, ledger.EVENT_COLUMNS),
}


def _output_path_error(target: Path) -> dict | None:
    if "\0" in str(target):
        return err("ledger", "invalid_output_path", "output_path must not contain a null byte")
    try:
        str(target).encode("utf-8")
    except UnicodeEncodeError:
        return err("ledger", "invalid_output_path", "output_path must be valid UTF-8 text")
    if not target.is_absolute():
        return err("ledger", "invalid_output_path", f"output_path must be absolute: {target}")
    if target.suffix.lower() != ".csv":
        return err("ledger", "invalid_output_path", f"output_path must end in .csv: {target}")
    if target.exists() and not target.is_file():
        return err("ledger", "invalid_output_path", f"output_path is not a regular file: {target}")
    return None


def _invalid_output_path_error(exc: OSError | RuntimeError) -> dict:
    """Log output-path handling failures and return the stable tool error."""
    log("WARNING", {"event": "invalid_output_path", "error": str(exc)})
    return err("ledger", "invalid_output_path", f"cannot use output_path: {exc}")


def export_ledger(
    output_path: str, status: str | None = None, since: str | None = None, mode: str = "jobs"
) -> dict:
    """Write the ledger as CSV to output_path.

    mode "jobs" (default): one row per job with its latest status and latest scores; status
    and since keep jobs with ANY matching event. mode "events": one row per status event
    (Date, Company, Title, URL, Status, Notes, Source), newest first; status and since filter
    the event itself, so each application keeps its own date. mode "contacts": same columns,
    only EDD-reportable events: notes starting "Contact method:" and statuses starting
    "Applied" or "Already applied". Use "contacts" for an EDD work-search log.

    output_path must be absolute and end in .csv. status matches the start of the status
    text (empty means no filter); since is YYYY-MM-DD (on or after). Text that a spreadsheet
    would run as a formula is prefixed with '.
    Error codes: invalid_mode, invalid_output_path, invalid_date, ledger_error.
    """
    if mode not in _EXPORT_MODES:
        allowed = ", ".join(sorted(_EXPORT_MODES))
        return err("ledger", "invalid_mode", f"mode must be one of {allowed}, got: {mode!r}")
    try:
        target = Path(output_path).expanduser()
        if error := _output_path_error(target):
            return error
    except (OSError, RuntimeError) as exc:
        return _invalid_output_path_error(exc)
    if error := date_error("since", since):
        return error
    query, columns = _EXPORT_MODES[mode]
    try:
        with closing(ledger.connect()) as conn:
            rows = query(conn, status_prefix=status, since=since)
    except (sqlite3.Error, OSError, RuntimeError, UnicodeError) as exc:
        return ledger_error(exc)
    try:
        write_text_atomic(target, csv_text(rows, columns))
    except OSError as exc:
        return _invalid_output_path_error(exc)
    return ok("", data={"path": str(target), "rows": len(rows)})
