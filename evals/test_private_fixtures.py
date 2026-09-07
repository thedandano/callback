"""Private fixture builder: copies a data dir, migrates + compiles it, and stages E2/E3 cases.

Uses only the committed Jane Doe fixtures — no personal data touches this test.
"""

from __future__ import annotations

import json
import os
import shutil
from pathlib import Path

import pytest

from evals.private_fixtures import REPO_ROOT, build

JANE_DOE = Path(__file__).resolve().parent / "tailor" / "jane-doe-backend"

TWO_BOARD_LAYOUT = [
    "compile/primary/golden/compiled_profile.json",
    "compile/primary/golden/index.md",
    "compile/primary/sections.json",
    "compile/primary/stories/story-001.md",
    "tailor/a/constraints.json",
    "tailor/a/keywords.json",
    "tailor/a/sections.json",
    "tailor/a/wiki/experience/story-001.md",
    "tailor/a/wiki/index.md",
    "tailor/b/constraints.json",
    "tailor/b/keywords.json",
    "tailor/b/sections.json",
    "tailor/b/wiki/experience/story-001.md",
    "tailor/b/wiki/index.md",
]


def _fake_source(tmp_path: Path) -> Path:
    """Build tmp_path/source/callback: one registered resume, one wiki page, empty stories."""
    source = tmp_path / "source" / "callback"
    (source / "inputs").mkdir(parents=True)
    (source / "inputs" / "primary.txt").write_text("eval resume placeholder", encoding="utf-8")

    wiki = source / "profile-wiki" / "primary"
    (wiki / "experience").mkdir(parents=True)
    (wiki / "sections.json").write_bytes((JANE_DOE / "sections.json").read_bytes())
    (wiki / "experience" / "story-001.md").write_bytes(
        (JANE_DOE / "wiki" / "experience" / "story-001.md").read_bytes()
    )

    accomplishments = {"schema_version": 2, "onboard_text": ""}
    (source / "accomplishments.json").write_text(json.dumps(accomplishments), encoding="utf-8")
    return source


def _fake_extract(tmp_path: Path) -> Path:
    """Build tmp_path/extract with two boards' markdown and golden keyword files."""
    extract = tmp_path / "extract"
    extract.mkdir()
    for board in ("a", "b"):
        (extract / f"{board}.md").write_text(f"# {board} job posting\n", encoding="utf-8")
        golden = {"title": "x", "required": ["Python"], "preferred": []}
        (extract / f"{board}.golden.json").write_text(json.dumps(golden), encoding="utf-8")
    return extract


def _snapshot(root: Path) -> dict[str, bytes]:
    return {str(p.relative_to(root)): p.read_bytes() for p in root.rglob("*") if p.is_file()}


def test_build_writes_compile_and_tailor_cases(tmp_path, monkeypatch):
    source = _fake_source(tmp_path)
    monkeypatch.setattr("evals.private_fixtures.EXTRACT_DIR", _fake_extract(tmp_path))
    dest = tmp_path / "dest"

    written = build(source, dest, ["a", "b"])

    actual = sorted(str(p.relative_to(dest)) for p in written)
    expected = TWO_BOARD_LAYOUT
    assert actual == expected


def test_build_never_touches_the_source(tmp_path, monkeypatch):
    source = _fake_source(tmp_path)
    monkeypatch.setattr("evals.private_fixtures.EXTRACT_DIR", _fake_extract(tmp_path))
    before = _snapshot(source)

    build(source, tmp_path / "dest", ["a"])

    after = _snapshot(source)
    assert after == before


def test_build_keeps_an_existing_constraints_file(tmp_path, monkeypatch):
    source = _fake_source(tmp_path)
    monkeypatch.setattr("evals.private_fixtures.EXTRACT_DIR", _fake_extract(tmp_path))
    dest = tmp_path / "dest"
    constraints_path = dest / "tailor" / "a" / "constraints.json"
    constraints_path.parent.mkdir(parents=True)
    existing = {"expect_no_coverage": True, "grounding_ratio": 70}
    constraints_path.write_text(json.dumps(existing), encoding="utf-8")

    build(source, dest, ["a"])

    actual = json.loads(constraints_path.read_text(encoding="utf-8"))
    expected = existing
    assert actual == expected


def test_build_refuses_a_destination_inside_the_repo(tmp_path):
    with pytest.raises(ValueError, match="refusing to write private fixtures inside the repo"):
        build(tmp_path, REPO_ROOT / "evals" / "private", ["a"])


def test_keywords_json_is_the_golden(tmp_path, monkeypatch):
    source = _fake_source(tmp_path)
    extract = _fake_extract(tmp_path)
    monkeypatch.setattr("evals.private_fixtures.EXTRACT_DIR", extract)
    dest = tmp_path / "dest"

    build(source, dest, ["a"])

    actual = (dest / "tailor" / "a" / "keywords.json").read_bytes()
    expected = (extract / "a.golden.json").read_bytes()
    assert actual == expected


def test_build_ignores_state_and_prior_output(tmp_path, monkeypatch):
    """Checkpoint DBs, the applications archive, and prior evals output never reach compile."""
    source = _fake_source(tmp_path)
    (source / "applications").mkdir()
    (source / "applications" / "x.json").write_text("{}", encoding="utf-8")
    (source / "apply-sessions.db").write_text("", encoding="utf-8")
    (source / "evals" / "old").mkdir(parents=True)
    (source / "evals" / "old" / "marker.txt").write_text("stale", encoding="utf-8")
    monkeypatch.setattr("evals.private_fixtures.EXTRACT_DIR", _fake_extract(tmp_path))
    dest = tmp_path / "dest"

    real_copytree = shutil.copytree
    ignored_names: set[str] = set()

    def _spy_copytree(
        src,
        dst,
        symlinks=False,
        ignore=None,
        copy_function=shutil.copy2,
        ignore_dangling_symlinks=False,
        dirs_exist_ok=False,
    ):
        # shutil's own recursion re-enters this patched name for every subdirectory;
        # only the top-level call (src is the fake source dir) is worth recording.
        if ignore is not None and Path(src) == source:
            ignored_names.update(ignore(src, os.listdir(src)))
        return real_copytree(
            src,
            dst,
            symlinks=symlinks,
            ignore=ignore,
            copy_function=copy_function,
            ignore_dangling_symlinks=ignore_dangling_symlinks,
            dirs_exist_ok=dirs_exist_ok,
        )

    monkeypatch.setattr("evals.private_fixtures.shutil.copytree", _spy_copytree)

    written = build(source, dest, ["a", "b"])

    actual_layout = sorted(str(p.relative_to(dest)) for p in written)
    expected_layout = TWO_BOARD_LAYOUT
    assert actual_layout == expected_layout

    actual_ignored = ignored_names
    expected_ignored = {"applications", "apply-sessions.db", "evals"}
    assert actual_ignored == expected_ignored
