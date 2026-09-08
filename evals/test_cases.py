"""Case discovery: the committed fixture root, sorted by name."""

from __future__ import annotations

import pytest

from evals import cases


def test_case_dirs_lists_cases_sorted_by_name(monkeypatch, tmp_path):
    root = tmp_path / "root"
    (root / "tailor" / "b-case").mkdir(parents=True)
    (root / "tailor" / "a-case").mkdir()
    (root / "tailor" / "stray.txt").write_text("")
    monkeypatch.setattr(cases, "ROOT", root)

    actual = cases.case_dirs("tailor")

    expected = [root / "tailor" / "a-case", root / "tailor" / "b-case"]
    assert actual == expected


def test_case_dirs_missing_kind_dir_is_empty(monkeypatch, tmp_path):
    root = tmp_path / "root"
    (root / "compile" / "jane").mkdir(parents=True)
    monkeypatch.setattr(cases, "ROOT", root)

    actual = cases.case_dirs("tailor")

    expected = []
    assert actual == expected


def test_case_dirs_rejects_unknown_kind():
    with pytest.raises(ValueError, match="unknown case kind 'extract'"):
        cases.case_dirs("extract")


def test_case_id_is_the_directory_name(tmp_path):
    actual = cases.case_id(tmp_path / "tailor" / "jane")

    expected = "jane"
    assert actual == expected
