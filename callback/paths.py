"""Every data directory callback reads or writes, and the atomic writers for them.

XDG_DATA_HOME moves the whole data root. CALLBACK_APPS_DIR moves only the
applications archive. Paths are computed on every call, so an env change or a
test patch takes effect without reloading modules.
"""

from __future__ import annotations

import json
import logging
import os
import tempfile
from pathlib import Path

logger = logging.getLogger(__name__)


def _xdg_root(env_var: str, default: Path) -> Path:
    """Resolve an XDG base-directory override, or `default` if unset or invalid.

    The XDG Base Directory spec requires these paths to be absolute and says
    a relative value must be treated as invalid (ignored, not resolved
    relative to cwd) — otherwise different processes with different working
    directories would silently land on different session stores.
    """
    if not (value := os.environ.get(env_var)):
        return default
    path = Path(value)
    if not path.is_absolute():
        logger.warning("ignoring relative %s=%r; must be absolute per the XDG spec", env_var, value)
        return default
    return path


def data_dir() -> Path:
    return _xdg_root("XDG_DATA_HOME", Path.home() / ".local" / "share") / "callback"


def state_dir() -> Path:
    return _xdg_root("XDG_STATE_HOME", Path.home() / ".local" / "state") / "callback"


def inputs_dir() -> Path:
    return data_dir() / "inputs"


def wiki_dir() -> Path:
    return data_dir() / "profile-wiki"


def apps_dir() -> Path:
    if env_path := os.environ.get("CALLBACK_APPS_DIR"):
        return Path(env_path)
    return data_dir() / "applications"


def _temp_root() -> Path:
    return Path(tempfile.gettempdir())


def session_dir() -> Path:
    """Session checkpoint DBs. Sessions last minutes (max seen: 1.9 h), so they live in the
    temp folder. The uid suffix and the 0o700 mode set by session_store keep resume text
    private even when TMPDIR is unset and this falls back to the shared /tmp. On Windows the
    folder relies on the temp folder being per-user (the default); a shared TEMP such as
    C:\\TEMP is not protected."""
    if not hasattr(os, "getuid"):  # Windows: the temp folder is already per-user
        return _temp_root() / "callback"
    return _temp_root() / f"callback-{os.getuid()}"


def apply_db_path() -> Path:
    return session_dir() / "apply-sessions.db"


def profile_db_path() -> Path:
    return session_dir() / "profile-sessions.db"


def log_path() -> Path:
    return state_dir() / "server.log"


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
    return _xdg_root("XDG_CONFIG_HOME", Path.home() / ".config") / "callback"


def env_file() -> Path:
    return config_dir() / "env.json"
