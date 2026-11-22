"""Input checks and error envelopes shared by the ledger tools."""

import datetime

from callback.config.logging import log_exception
from callback.tools.envelope import err


def is_iso_date(value: str) -> bool:
    """True only for a real YYYY-MM-DD; text comparison of dates breaks on other shapes."""
    try:
        return datetime.date.fromisoformat(value).isoformat() == value
    except ValueError:
        return False


def date_error(name: str, value: str | None) -> dict | None:
    if value is None or is_iso_date(value):
        return None
    return err("ledger", "invalid_date", f"{name} must be YYYY-MM-DD, got: {value!r}")


def identity_error(url: str | None, company: str | None, title: str | None) -> dict | None:
    if (url or "").strip() or ((company or "").strip() and (title or "").strip()):
        return None
    return err(
        "ledger", "missing_job_identity", "Give a URL, or a company and title.", retriable=False
    )


def ledger_error(exc: Exception) -> dict:
    """Envelope for a ledger that cannot be opened, read, or written. Call from an except."""
    log_exception({"tool": "ledger", "event": "ledger_error", "error": str(exc)})
    return err(
        "ledger", "ledger_error", f"could not read or write the ledger: {exc}", retriable=True
    )
