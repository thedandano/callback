"""Private fixture builder: copies a data dir, migrates + compiles it, and stages E2/E3 cases.

Uses only the committed Jane Doe fixtures — no personal data touches this test.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from evals.private_fixtures import REPO_ROOT, build

JANE_DOE = Path(__file__).resolve().parent / "tailor" / "jane-doe-backend"


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
    expected = [
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
