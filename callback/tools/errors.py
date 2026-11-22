"""Error envelopes for session-store and unexpected failures."""

import sqlite3
from collections.abc import Callable
from typing import Any

from callback.config.logging import log_exception
from callback.models.envelope import err


def graph_or_err(factory: Callable[[], Any], session_id: str | None) -> tuple[Any, dict | None]:
    """Build a graph, or return an error envelope when the session store cannot be opened."""
    try:
        return factory(), None
    except PermissionError as exc:
        log_exception({"event": "unsafe_session_dir", "session_id": session_id})
        return None, err(
            stage="session_store",
            code="unsafe_session_dir",
            message=str(exc),
            session_id=session_id,
            retriable=False,
        )
    except (sqlite3.Error, OSError) as exc:
        # Locked, corrupt, read-only, or full session store: report it, don't leak a raw error.
        log_exception({"event": "session_store_error", "session_id": session_id})
        return None, err(
            stage="session_store",
            code="session_store_error",
            message=f"unable to open session store: {exc}",
            session_id=session_id,
            retriable=True,
        )


def unexpected_error(stage: str, session_id: str) -> dict:
    """Log the active exception with traceback and return an unexpected_error envelope."""
    log_exception({"tool": stage, "session_id": session_id, "event": "unexpected_error"})
    return err(
        stage=stage,
        code="unexpected_error",
        message=f"unexpected {stage} failure; inspect callback logs",
        session_id=session_id,
        retriable=False,
    )
