"""E3: compile_profile rebuilds index.md byte-for-byte and never rewrites a story page.

Runs in CI on the committed Jane Doe case and, when the private root exists,
on the user's real stories too.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from evals.cases import case_dirs, case_id
from evals.compile_support import compile_case, install_case

CASES = case_dirs("compile")
HAND_EDIT = "\n\n**Impact:** Edited by hand after compile; this line must survive.\n"


def _data_root(wiki: Path) -> Path:
    """Get the data root from a wiki path (wiki is <root>/callback/profile-wiki/primary)."""
    return wiki.parents[3]


@pytest.fixture(params=CASES, ids=[case_id(c) for c in CASES])
def staged(request, tmp_path, monkeypatch):
    monkeypatch.setenv("XDG_DATA_HOME", str(tmp_path))
    monkeypatch.delenv("CALLBACK_APPS_DIR", raising=False)
    wiki = install_case(request.param, tmp_path)
    return request.param, wiki


def test_index_is_byte_identical(staged):
    case_dir, wiki = staged
    compile_case(_data_root(wiki))

    actual = (wiki / "index.md").read_bytes()

    expected = (case_dir / "golden" / "index.md").read_bytes()
    assert actual == expected


def test_skills_index_and_orphans_match_golden(staged):
    case_dir, wiki = staged
    profile = compile_case(_data_root(wiki))
    golden = json.loads((case_dir / "golden" / "compiled_profile.json").read_text(encoding="utf-8"))

    actual = {
        "skills_index": profile["skills_index"],
        "orphaned_skills": profile["orphaned_skills"],
    }

    expected = {
        "skills_index": golden["skills_index"],
        "orphaned_skills": golden["orphaned_skills"],
    }
    assert actual == expected


def test_hand_edited_story_survives_compile(staged):
    _, wiki = staged
    page = wiki / "experience" / "story-001.md"
    edited = page.read_text(encoding="utf-8").rstrip("\n") + HAND_EDIT
    page.write_text(edited, encoding="utf-8")
    compile_case(_data_root(wiki))

    actual = page.read_text(encoding="utf-8")

    expected = edited
    assert actual == expected
