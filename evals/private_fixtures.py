"""Build the private E2/E3 cases from a copy of the real callback data dir.

The real data is copied to a scratch dir, migrated (legacy JSON stories become
pages) and compiled there, and the results are written under the private root.
Never modifies existing files under the data dir; all output goes under
--dest (default ~/.local/share/callback/evals). The destination must be
outside the repo.
"""

from __future__ import annotations

import json
import logging
import os
import shutil
import tempfile
from pathlib import Path

from callback.repository.stories import migrate_legacy_stories
from evals.compile_support import compile_case
from evals.tailor_checks import DEFAULT_GROUNDING_RATIO

logger = logging.getLogger("callback.evals")

REPO_ROOT = Path(__file__).resolve().parent.parent
EXTRACT_DIR = REPO_ROOT / "evals" / "extract"
DEFAULT_CONSTRAINTS = {"expect_no_coverage": False, "grounding_ratio": DEFAULT_GROUNDING_RATIO}

# Only inputs/, profile-wiki/, and accomplishments.json matter here; skip the
# checkpoint DBs, the applications archive, and any prior evals output (the
# default --dest lives under the default --source) so the copy stays small.
_COPY_IGNORE = (
    "*.db",
    "*.db-*",
    "applications",
    "evals",
    "*.bak",
    "*.preonboard-*",
    "*.reonboard-*",
    "*.k8sfix-*",
    "reonboard-*",
    "profile-wiki.preonboard-*",
)


def _copy(src: Path, dest: Path, written: list[Path]) -> None:
    dest.parent.mkdir(parents=True, exist_ok=True)
    shutil.copy(src, dest)
    written.append(dest)


def _write_json(path: Path, data: object, written: list[Path]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    written.append(path)


def _compiled_copy(source: Path, scratch: Path, label: str) -> Path:
    """Copy source under scratch/callback, migrate + compile there, return the wiki root."""
    shutil.copytree(source, scratch / "callback", ignore=shutil.ignore_patterns(*_COPY_IGNORE))
    previous = os.environ.get("XDG_DATA_HOME")
    os.environ["XDG_DATA_HOME"] = str(scratch)
    try:
        migrated = migrate_legacy_stories(label)
        compile_case(scratch, label)
    finally:
        if previous is None:
            os.environ.pop("XDG_DATA_HOME", None)
        else:
            os.environ["XDG_DATA_HOME"] = previous
    logger.info("compiled a copy of %s (migrated %d legacy stories)", source, migrated)
    return scratch / "callback" / "profile-wiki" / label


def _reset_generated_dir(path: Path) -> None:
    """Remove a fully generated subtree before rewriting it, so a story deleted or renamed
    in the real profile doesn't survive as a stale file in the fixture."""
    if path.exists():
        logger.info("replacing existing generated directory %s", path)
        shutil.rmtree(path)


def _write_compile_case(wiki: Path, compiled_json: Path, dest: Path, label: str) -> list[Path]:
    written: list[Path] = []
    case = dest / "compile" / label
    _reset_generated_dir(case / "stories")
    _reset_generated_dir(case / "golden")
    for story in sorted((wiki / "experience").glob("story-*.md")):
        _copy(story, case / "stories" / story.name, written)
    _copy(wiki / "sections.json", case / "sections.json", written)
    _copy(wiki / "index.md", case / "golden" / "index.md", written)
    _copy(compiled_json, case / "golden" / "compiled_profile.json", written)
    return written


def _write_tailor_case(wiki: Path, dest: Path, board: str) -> list[Path]:
    written: list[Path] = []
    case = dest / "tailor" / board
    _reset_generated_dir(case / "wiki")
    _copy(wiki / "sections.json", case / "sections.json", written)
    _copy(EXTRACT_DIR / f"{board}.golden.json", case / "keywords.json", written)
    _copy(wiki / "index.md", case / "wiki" / "index.md", written)
    for story in sorted((wiki / "experience").glob("story-*.md")):
        _copy(story, case / "wiki" / "experience" / story.name, written)
    constraints = case / "constraints.json"
    if constraints.exists():
        logger.info("%s exists; keeping it", constraints)
    else:
        _write_json(constraints, DEFAULT_CONSTRAINTS, written)
    return written


def build(source: Path, dest: Path, boards: list[str], label: str = "primary") -> list[Path]:
    """Write the private compile case and one tailor case per board. Returns the paths written."""
    if dest.resolve().is_relative_to(REPO_ROOT):
        raise ValueError(f"refusing to write private fixtures inside the repo: {dest}")
    scratch = Path(tempfile.mkdtemp(prefix="callback-eval-fixtures-"))
    try:
        wiki = _compiled_copy(source, scratch, label)
        compiled_json = scratch / "callback" / "compiled_profile.json"
        written = _write_compile_case(wiki, compiled_json, dest, label)
        for board in boards:
            written.extend(_write_tailor_case(wiki, dest, board))
    finally:
        try:
            shutil.rmtree(scratch)
        except OSError as exc:
            logger.warning("scratch dir %s not removed: %s", scratch, exc)
    return written
