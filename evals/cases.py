"""Where eval cases live: the committed synthetic set plus a private root outside git."""

from __future__ import annotations

import os
from pathlib import Path

PUBLIC_ROOT = Path(__file__).resolve().parent
PRIVATE_ROOT_ENV = "CALLBACK_EVALS_DIR"
CASE_KINDS = ("tailor", "compile")


def private_root() -> Path:
    """Real resume, wiki, and stories live here. Never inside the repo."""
    if env := os.environ.get(PRIVATE_ROOT_ENV):
        return Path(env)
    return Path.home() / ".local" / "share" / "callback" / "evals"


def case_dirs(kind: str) -> list[Path]:
    """Case directories for one kind, committed cases first, then private ones."""
    if kind not in CASE_KINDS:
        raise ValueError(f"unknown case kind {kind!r}; expected one of {CASE_KINDS}")
    found: list[Path] = []
    for root in (PUBLIC_ROOT / kind, private_root() / kind):
        if root.is_dir():
            found.extend(sorted(p for p in root.iterdir() if p.is_dir()))
    return found


def case_id(case_dir: Path) -> str:
    scope = "public" if case_dir.is_relative_to(PUBLIC_ROOT) else "private"
    return f"{scope}:{case_dir.name}"
