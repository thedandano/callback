"""Open a session checkpoint DB with callback's types allowlisted and stale threads pruned.

Sessions finish in minutes (433 apply sessions measured: median ~1 min, max 1.9 h), but
nothing used to delete them, so the DBs grew to 160 MB. Pruning on open keeps them bounded
even though the temp folder's own cleanup skips files that are accessed every day.
"""

from __future__ import annotations

import contextlib
import json
import logging
import os
import sqlite3
import stat
import uuid
from datetime import UTC, datetime, timedelta
from pathlib import Path

from langgraph.checkpoint.serde.jsonplus import JsonPlusSerializer
from langgraph.checkpoint.sqlite import SqliteSaver

logger = logging.getLogger(__name__)

SESSION_MAX_AGE = timedelta(hours=24)
# Types LangGraph's msgpack serde must be allowed to rebuild from a checkpoint.
_ALLOWED_TYPES = [("callback.state", "TailoredResume")]
_GREGORIAN_EPOCH = datetime(1582, 10, 15, tzinfo=UTC)


def checkpoint_time(checkpoint_id: str) -> datetime:
    """Decode the creation time LangGraph stores in a uuid6 checkpoint id."""
    high = uuid.UUID(checkpoint_id).int >> 64
    ticks = ((high >> 16) << 12) | (high & 0xFFF)  # 100 ns intervals since 1582-10-15
    return _GREGORIAN_EPOCH + timedelta(microseconds=ticks // 10)


def _stale_thread_ids(conn: sqlite3.Connection, now: datetime) -> list[str]:
    # uuid6 ids sort by time as strings, so MAX() is each thread's newest checkpoint.
    rows = conn.execute(
        "SELECT thread_id, MAX(checkpoint_id) FROM checkpoints GROUP BY thread_id"
    ).fetchall()
    return [tid for tid, cid in rows if now - checkpoint_time(cid) > SESSION_MAX_AGE]


def _delete_if_still_stale(saver: SqliteSaver, thread_id: str, now: datetime) -> bool:
    """Delete a thread unless another process wrote a fresh checkpoint since it was picked.

    BEGIN IMMEDIATE takes the write lock first, so the re-check and the delete are one step.
    """
    with saver.cursor() as cur:
        cur.execute("BEGIN IMMEDIATE")
        newest = cur.execute(
            "SELECT MAX(checkpoint_id) FROM checkpoints WHERE thread_id = ?", (thread_id,)
        ).fetchone()[0]
        if newest is not None and now - checkpoint_time(newest) <= SESSION_MAX_AGE:
            return False
        cur.execute("DELETE FROM checkpoints WHERE thread_id = ?", (thread_id,))
        cur.execute("DELETE FROM writes WHERE thread_id = ?", (thread_id,))
    return True


def _prune(saver: SqliteSaver, conn: sqlite3.Connection, db_path: Path, now: datetime) -> None:
    deleted = [
        thread_id
        for thread_id in _stale_thread_ids(conn, now)
        if _delete_if_still_stale(saver, thread_id, now)
    ]
    if not deleted:
        return
    try:
        conn.execute("VACUUM")
    except sqlite3.OperationalError as exc:
        # Another process holds the DB; rows are already deleted, only the file shrink waits.
        logger.warning(
            json.dumps({"event": "session_vacuum_skipped", "db": str(db_path), "error": str(exc)})
        )
    logger.info(
        json.dumps({"event": "session_prune", "db": str(db_path), "threads_deleted": len(deleted)})
    )


def _ensure_private_dir(folder: Path) -> None:
    """Create the session folder, or refuse one we don't own, a symlink, or one others can read."""
    folder.parent.mkdir(parents=True, exist_ok=True)
    # An existing folder is fine here: the checks below decide whether it is safe.
    with contextlib.suppress(FileExistsError):
        os.mkdir(folder, 0o700)
        os.chmod(folder, 0o700)  # a hardened umask can strip the owner's execute bit
    info = os.lstat(folder)
    if not stat.S_ISDIR(info.st_mode):
        reason = "not a real directory (symlink?)"
    elif not hasattr(os, "getuid"):
        return  # Windows: the temp folder is already per-user, and there are no uid or mode bits.
    elif info.st_uid != os.getuid():
        reason = "owned by another user"
    elif info.st_mode & 0o077:
        reason = f"permissions {stat.S_IMODE(info.st_mode):o} let others in"
    elif info.st_mode & 0o700 != 0o700:
        reason = f"permissions {stat.S_IMODE(info.st_mode):o} lock the owner out"
    else:
        return
    raise PermissionError(f"refusing unsafe session dir {folder}: {reason}")


def open_checkpointer(db_path: Path, now: datetime | None = None) -> SqliteSaver:
    """Open the session DB, allowlist callback's types, and prune threads idle over 24 h.

    ponytail: get_apply_graph() and get_profile_graph() are cached for the life of the
    process, so this prune runs once per server start. If a long-lived server grows,
    prune from submit_keywords instead.
    """
    _ensure_private_dir(db_path.parent)
    conn = sqlite3.connect(str(db_path), check_same_thread=False)
    # with_allowlist() is a no-op under LangGraph's default permissive mode, so build the
    # serializer explicitly: only SAFE types plus _ALLOWED_TYPES, whatever the environment says.
    serde = JsonPlusSerializer(allowed_msgpack_modules=_ALLOWED_TYPES)
    saver = SqliteSaver(conn, serde=serde)
    saver.setup()
    logger.info(json.dumps({"event": "session_db_open", "db": str(db_path)}))
    _prune(saver, conn, db_path, now or datetime.now(UTC))
    return saver
