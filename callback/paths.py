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
        try:
            # Cross-filesystem shutil.move copies then unlinks — not atomic, so
            # stage under a temp name first. The final rename is same-filesystem
            # (both under target.parent) and atomic, so `dst` itself never holds
            # a truncated file, only ever the complete one or none at all.
            shutil.move(str(src), str(staging))
            staging.replace(dst)
        except OSError as exc:
            staging.unlink(missing_ok=True)
            raise OSError(f"failed to move legacy file {src} to {dst}: {exc}") from exc
    logger.info("moved legacy file %s to %s", legacy, target)


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
