"""Every data directory callback reads or writes, and the atomic writers for them.

XDG_DATA_HOME moves the whole data root. CALLBACK_APPS_DIR moves only the
default PDF folder. Paths are computed on every call, so an env change or a
test patch takes effect without reloading modules.
"""

from __future__ import annotations

import hashlib
import json
import logging
import os
import re
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


def _ledger_path_impl() -> Path:
    return data_dir() / "ledger.db"


ledger_path = _ledger_path_impl  # tests swap ledger_path; this keeps the real one reachable


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
        with os.fdopen(fd, "w", encoding="utf-8", newline="") as tmp:
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


SLUG_MAX_LENGTH = 80
_SLUG_HASH_LENGTH = 8
_SLUG_LOSSY_CHARS = re.compile(r"[^A-Za-z0-9\s\-.,&/'():]")


def slug(*parts: str | None) -> str:
    """Folder-safe name: lowercase words joined by hyphens, e.g. 'acme-senior-engineer'.

    Names over SLUG_MAX_LENGTH are cut and given a short hash of the full name, so they stay
    under filesystem limits and two long names do not collide.
    """
    joined = " ".join(p for p in parts if p)
    full = re.sub(r"[^a-z0-9]+", "-", joined.lower()).strip("-") or "job"
    lossy = _SLUG_LOSSY_CHARS.search(joined) is not None
    if len(full) <= SLUG_MAX_LENGTH and not lossy:
        return full
    # Punctuation or non-ASCII text ("C++" vs "C#") collapses to the same words, so hash the
    # original text. Plain long names keep hashing the folded name, as before.
    digest = hashlib.sha1((joined if lossy else full).encode()).hexdigest()[:_SLUG_HASH_LENGTH]
    head = full[: SLUG_MAX_LENGTH - _SLUG_HASH_LENGTH - 1].strip("-")
    return f"{head}-{digest}"
