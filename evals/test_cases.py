"""Case discovery: committed cases first, private root second, env override."""

from __future__ import annotations

from pathlib import Path

import pytest

from evals import cases


def test_private_root_defaults_under_home(monkeypatch, tmp_path):
    monkeypatch.delenv("CALLBACK_EVALS_DIR", raising=False)
    monkeypatch.setattr(Path, "home", lambda: tmp_path)

    actual = cases.private_root()

    expected = tmp_path / ".local" / "share" / "callback" / "evals"
    assert actual == expected


def test_private_root_honors_env(monkeypatch, tmp_path):
    monkeypatch.setenv("CALLBACK_EVALS_DIR", str(tmp_path / "mine"))

    actual = cases.private_root()

    expected = tmp_path / "mine"
    assert actual == expected


def test_case_dirs_lists_public_then_private(monkeypatch, tmp_path):
    public = tmp_path / "public"
    private = tmp_path / "private"
    (public / "tailor" / "b-case").mkdir(parents=True)
    (public / "tailor" / "a-case").mkdir()
    (public / "tailor" / "stray.txt").write_text("")
    (private / "tailor" / "real").mkdir(parents=True)
    monkeypatch.setattr(cases, "PUBLIC_ROOT", public)
    monkeypatch.setenv("CALLBACK_EVALS_DIR", str(private))

    actual = cases.case_dirs("tailor")

    expected = [
        public / "tailor" / "a-case",
        public / "tailor" / "b-case",
        private / "tailor" / "real",
    ]
    assert actual == expected


def test_case_dirs_without_private_root(monkeypatch, tmp_path):
    public = tmp_path / "public"
    (public / "compile" / "jane").mkdir(parents=True)
    monkeypatch.setattr(cases, "PUBLIC_ROOT", public)
    monkeypatch.setenv("CALLBACK_EVALS_DIR", str(tmp_path / "missing"))

    actual = cases.case_dirs("compile")

    expected = [public / "compile" / "jane"]
    assert actual == expected


def test_case_dirs_rejects_unknown_kind():
    with pytest.raises(ValueError, match="unknown case kind 'extract'"):
        cases.case_dirs("extract")


def test_case_id_marks_scope(monkeypatch, tmp_path):
    public = tmp_path / "public"
    monkeypatch.setattr(cases, "PUBLIC_ROOT", public)

    actual = [
        cases.case_id(public / "tailor" / "jane"),
        cases.case_id(tmp_path / "p" / "real"),
    ]

    expected = ["public:jane", "private:real"]
    assert actual == expected
