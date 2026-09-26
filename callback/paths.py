"""Every data directory callback reads or writes, and the atomic writers for them.

XDG_DATA_HOME moves the whole data root. CALLBACK_APPS_DIR moves only the
applications archive. Paths are computed on every call, so an env change or a
test patch takes effect without reloading modules.
"""

from __future__ import annotations

import json
import logging
import os
import shutil
import tempfile
import time
from collections.abc import Iterator
from contextlib import contextmanager
from pathlib import Path

logger = logging.getLogger(__name__)


def data_dir() -> Path:
    if xdg_data_home := os.environ.get("XDG_DATA_HOME"):
        return Path(xdg_data_home) / "callback"
    return Path.home() / ".local" / "share" / "callback"


def state_dir() -> Path:
    if xdg_state_home := os.environ.get("XDG_STATE_HOME"):
        return Path(xdg_state_home) / "callback"
    return Path.home() / ".local" / "state" / "callback"


def inputs_dir() -> Path:
    return data_dir() / "inputs"


def wiki_dir() -> Path:
    return data_dir() / "profile-wiki"


def apps_dir() -> Path:
    if env_path := os.environ.get("CALLBACK_APPS_DIR"):
        return Path(env_path)
    return data_dir() / "applications"


def apply_db_path() -> Path:
    return state_dir() / "apply-sessions.db"


def profile_db_path() -> Path:
    return state_dir() / "profile-sessions.db"


def log_path() -> Path:
    return state_dir() / "server.log"


def _resolve_pending_staging(src: Path, dst: Path, staging: Path) -> bool:
    """Handle a leftover `.migrating` file from an interrupted earlier attempt.

    Returns True if this suffix is now fully handled (caller should move on to
    the next one), False if the copy still needs to run.
    """
    if not staging.exists():
        return False
    if src.exists():
        # shutil.move below only unlinks src after its copy into staging fully
        # succeeds, so src still being here means that copy was interrupted
        # partway — staging may hold a truncated file. Discard it and redo
        # the copy from the still-intact source.
        staging.unlink()
        return False
    # src is already gone, so the copy into staging did complete; only the
    # rename below was interrupted. Finish that rename.
    staging.replace(dst)
    return True


def _copy_and_publish_staged(src: Path, dst: Path, staging: Path) -> None:
    """Copy `src` to `staging`, then atomically rename it to `dst`.

    Cross-filesystem shutil.move copies then unlinks — not atomic, so this
    stages under a temp name first. The final rename is same-filesystem (both
    under dst.parent) and atomic, so `dst` itself never holds a truncated
    file, only ever the complete one or none at all.
    """
    try:
        shutil.move(str(src), str(staging))
    except OSError as exc:
        # The copy itself failed partway; src may still exist (safe to retry
        # from) or the removal at the end of shutil.move failed after a real
        # copy (also safe: the next attempt's _resolve_pending_staging sees
        # src still present and redoes the copy). Either way, a partial file
        # may be sitting in staging — discard it.
        staging.unlink(missing_ok=True)
        raise OSError(f"failed to copy legacy file {src} to staging: {exc}") from exc
    try:
        staging.replace(dst)
    except OSError as exc:
        # The copy into staging fully succeeded (shutil.move already unlinked
        # src) — staging holds the only complete copy. Leave it in place; the
        # next attempt's _resolve_pending_staging finishes this same rename
        # instead of losing the last copy of the data.
        raise OSError(f"failed to publish migrated file {dst}: {exc}") from exc


_MIGRATION_LOCK_WAIT_S = 30.0
_MIGRATION_LOCK_POLL_S = 0.2


@contextmanager
def _migration_lock(target: Path) -> Iterator[bool]:
    """Claim exclusive ownership of migrating into `target`.

    Yields True if this call claimed the lock (and releases it on exit). If
    another process already holds it, waits for either `target` to appear
    (that process published it — done, nothing left for us to do) or the
    lock to be released (that process finished some other way — worth a
    fresh attempt at claiming it) before giving up and yielding False. This
    keeps a concurrent second process from opening (and thereby creating) an
    empty database at `target` while the winner is still mid-copy.

    ponytail: no liveness check, so a process that crashes while holding the
    lock makes every waiter time out and yield False — legacy stays in place
    (never destroyed), just unmigrated until the stale lock file is removed
    by hand. Acceptable for a one-time legacy-DB migration on a single-user
    local tool; add a PID check if this ever needs to self-heal.
    """
    lock_path = Path(f"{target}.migrating.lock")
    deadline = time.monotonic() + _MIGRATION_LOCK_WAIT_S
    while True:
        try:
            fd = os.open(str(lock_path), os.O_CREAT | os.O_EXCL | os.O_WRONLY)
            break
        except FileExistsError:
            if target.exists() or time.monotonic() >= deadline:
                yield False
                return
            time.sleep(_MIGRATION_LOCK_POLL_S)
    os.close(fd)
    try:
        yield True
    finally:
        lock_path.unlink(missing_ok=True)


def move_legacy_file(legacy: Path, target: Path) -> None:
    """Move a legacy file, plus its SQLite -wal/-shm siblings, to a new location.

    No-op if `legacy` does not exist. If `target` already exists, `legacy` is left in
    place untouched (never overwritten) and a warning is logged.
    """
    staging_pending = any(
        Path(f"{target}{suffix}.migrating").exists() for suffix in ("-wal", "-shm", "")
    )
    if not legacy.exists() and not staging_pending:
        # Nothing to migrate — unless an earlier attempt's copy fully finished
        # (unlinking `legacy` itself) before it could rename staging to target;
        # `staging_pending` catches that so the rename below still gets to run.
        return
    if target.exists():
        logger.warning("legacy file %s left in place; %s already exists", legacy, target)
        return
    target.parent.mkdir(parents=True, exist_ok=True)
    with _migration_lock(target) as acquired:
        if not acquired:
            # Another process (e.g. a second MCP host's own `callback serve`
            # pointed at the same state dir) is already migrating this same
            # target — let it finish rather than racing it for the shared
            # `.migrating` staging path.
            logger.info("migration for %s already in progress elsewhere; skipping", target)
            return
        if target.exists():
            # The lock holder published target and released the lock between
            # our last failed open attempt and this one, and we won the now-
            # free lock on retry. Re-running the migration here would
            # overwrite their just-published data with a stale copy.
            logger.info("legacy file %s already migrated to %s elsewhere", legacy, target)
            return
        _migrate_all_suffixes(legacy, target)
    logger.info("moved legacy file %s to %s", legacy, target)


def _migrate_all_suffixes(legacy: Path, target: Path) -> None:
    # -wal/-shm move first, the main file last: if this is interrupted partway
    # through, the original main file is still at `legacy`, never orphaned at
    # `target` without the WAL that may hold uncommitted data.
    for suffix in ("-wal", "-shm", ""):
        src = Path(f"{legacy}{suffix}")
        dst = Path(f"{target}{suffix}")
        staging = Path(f"{dst}.migrating")
        if _resolve_pending_staging(src, dst, staging):
            continue
        if not src.exists():
            continue
        _copy_and_publish_staged(src, dst, staging)


def write_text_atomic(path: Path, content: str) -> None:
    """Write via a sibling temp file and rename, so readers never see a partial file.

    Any failure in write, close (buffered flush), or rename removes the temp file, so
    repeated failures do not pile up next to the real file.
    """
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, name = tempfile.mkstemp(dir=path.parent, prefix=f".{path.name}.", suffix=".tmp")
    tmp_path = Path(name)
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as tmp:
            tmp.write(content)
        tmp_path.replace(path)
    except BaseException:
        # Re-raised below; the only job here is to leave no temp file behind.
        tmp_path.unlink(missing_ok=True)
        raise


def write_json_atomic(path: Path, data: object) -> None:
    write_text_atomic(path, json.dumps(data))


def config_dir() -> Path:
    if xdg_config_home := os.environ.get("XDG_CONFIG_HOME"):
        return Path(xdg_config_home) / "callback"
    return Path.home() / ".config" / "callback"


def env_file() -> Path:
    return config_dir() / "env.json"
