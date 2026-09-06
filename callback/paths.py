"""Every data directory callback reads or writes, and the atomic writers for them.

XDG_DATA_HOME moves the whole data root. CALLBACK_APPS_DIR moves only the
applications archive. Paths are computed on every call, so an env change or a
test patch takes effect without reloading modules.
"""

from __future__ import annotations

import json
import os
import tempfile
from pathlib import Path


def data_dir() -> Path:
    if xdg_data_home := os.environ.get("XDG_DATA_HOME"):
        return Path(xdg_data_home) / "callback"
    return Path.home() / ".local" / "share" / "callback"


def state_dir() -> Path:
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
    return data_dir() / "apply-sessions.db"


def profile_db_path() -> Path:
    return data_dir() / "profile-sessions.db"


def write_text_atomic(path: Path, content: str) -> None:
    """Write via a sibling temp file and rename, so readers never see a partial file."""
    path.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.NamedTemporaryFile("w", encoding="utf-8", dir=path.parent, delete=False) as tmp:
        tmp_path = Path(tmp.name)
        try:
            tmp.write(content)
        except Exception:
            tmp_path.unlink(missing_ok=True)
            raise
    tmp_path.replace(path)


def write_json_atomic(path: Path, data: object) -> None:
    write_text_atomic(path, json.dumps(data))
