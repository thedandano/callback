"""Atomic file writers, so readers never see a partial file."""

from __future__ import annotations

import json
import os
import tempfile
from pathlib import Path


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
