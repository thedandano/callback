"""Server logging: stderr plus an optional rotating-at-startup log file.

The logger name stays "callback.server" so existing log routing and caplog filters
keep working after the move out of server.py.
"""

import datetime
import json
import logging
import os
import sys
import traceback
from pathlib import Path

_LOG_FORMAT = "%(message)s"  # messages are already JSON strings
_LOG_ROTATE_BYTES = 10 * 1024 * 1024  # 10 MB; one previous log is kept as server.log.1
_log_path: Path | None = None

logger = logging.getLogger("callback.server")


def _rotate_if_large(path: Path) -> None:
    """Move an oversized log aside before opening it.

    ponytail: rotates only at startup, not mid-run, because several `callback serve`
    processes can share one log and RotatingFileHandler breaks when they do. A process
    that runs for weeks can still grow its log; switch to a per-process log if that happens.
    A second server started after the log passes 10 MB renames the file while the first still
    writes to it, so the first server's lines go to server.log.1 until it restarts. The
    upgrade path is per-process log files.
    """
    if path.exists() and path.stat().st_size > _LOG_ROTATE_BYTES:
        path.replace(path.with_name(f"{path.name}.1"))


def configure_logging(log_path: str | Path | None = None) -> None:
    """Configure stderr logging plus an optional server log file.

    LOG_LEVEL is read here, not at import, so a value loaded from env.json applies.
    """
    global _log_path
    level = os.environ.get("LOG_LEVEL", "INFO").upper()
    logging.basicConfig(
        level=level,
        format=_LOG_FORMAT,
        stream=sys.stderr,
    )
    if log_path is None:
        return

    path = Path(log_path).expanduser()
    root = logging.getLogger()
    root.setLevel(level)
    for handler in root.handlers:
        if getattr(handler, "_callback_log_path", None) == str(path):
            _log_path = path
            return

    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        _rotate_if_large(path)
        handler = logging.FileHandler(path, encoding="utf-8")
    except OSError as exc:
        _log_path = None
        root.warning(
            json.dumps(
                {
                    "event": "file_logging_disabled",
                    "path": str(path),
                    "error": str(exc),
                }
            )
        )
        return

    handler.setFormatter(logging.Formatter(_LOG_FORMAT))
    handler.setLevel(level)
    handler._callback_log_path = str(path)  # type: ignore[attr-defined]
    root.addHandler(handler)
    _log_path = path


def current_log_path() -> Path | None:
    """Return the active server log file, or None when file logging is off."""
    return _log_path


def log(level: str, payload: dict) -> None:
    """Log a structured JSON message."""
    payload["timestamp"] = datetime.datetime.now(datetime.UTC).isoformat()
    payload["level"] = level
    logger.log(getattr(logging, level, logging.INFO), json.dumps(payload))


def log_exception(payload: dict) -> None:
    """Log an exception payload plus traceback to stderr and the server log file."""
    payload["traceback"] = traceback.format_exc()
    logger.exception(json.dumps(payload))
