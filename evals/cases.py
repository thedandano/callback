"""Where eval cases live: the committed synthetic fixture set."""

from __future__ import annotations

from pathlib import Path

ROOT = Path(__file__).resolve().parent
CASE_KINDS = ("tailor", "compile")


def case_dirs(kind: str) -> list[Path]:
    """Case directories for one kind, sorted by name."""
    if kind not in CASE_KINDS:
        raise ValueError(f"unknown case kind {kind!r}; expected one of {CASE_KINDS}")
    root = ROOT / kind
    if not root.is_dir():
        return []
    return sorted(p for p in root.iterdir() if p.is_dir())


def case_id(case_dir: Path) -> str:
    return case_dir.name
