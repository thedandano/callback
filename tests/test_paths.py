import json
from pathlib import Path

from callback import paths


def test_data_dir_defaults_under_home(monkeypatch, tmp_path: Path):
    monkeypatch.delenv("XDG_DATA_HOME", raising=False)
    monkeypatch.setattr(Path, "home", staticmethod(lambda: tmp_path))
    actual = {
        "data": paths.data_dir(),
        "inputs": paths.inputs_dir(),
        "wiki": paths.wiki_dir(),
        "apps": paths.apps_dir(),
        "apply_db": paths.apply_db_path(),
        "profile_db": paths.profile_db_path(),
        "state": paths.state_dir(),
    }
    root = tmp_path / ".local" / "share" / "callback"
    expected = {
        "data": root,
        "inputs": root / "inputs",
        "wiki": root / "profile-wiki",
        "apps": root / "applications",
        "apply_db": root / "apply-sessions.db",
        "profile_db": root / "profile-sessions.db",
        "state": tmp_path / ".local" / "state" / "callback",
    }
    assert actual == expected


def test_xdg_data_home_moves_every_data_path(monkeypatch, tmp_path: Path):
    monkeypatch.setenv("XDG_DATA_HOME", str(tmp_path / "xdg"))
    monkeypatch.delenv("CALLBACK_APPS_DIR", raising=False)
    actual = {
        "data": paths.data_dir(),
        "inputs": paths.inputs_dir(),
        "wiki": paths.wiki_dir(),
        "apps": paths.apps_dir(),
        "apply_db": paths.apply_db_path(),
        "profile_db": paths.profile_db_path(),
    }
    root = tmp_path / "xdg" / "callback"
    expected = {
        "data": root,
        "inputs": root / "inputs",
        "wiki": root / "profile-wiki",
        "apps": root / "applications",
        "apply_db": root / "apply-sessions.db",
        "profile_db": root / "profile-sessions.db",
    }
    assert actual == expected


def test_callback_apps_dir_overrides_only_the_archive(monkeypatch, tmp_path: Path):
    monkeypatch.setenv("XDG_DATA_HOME", str(tmp_path / "xdg"))
    monkeypatch.setenv("CALLBACK_APPS_DIR", str(tmp_path / "apps"))
    actual = {"apps": paths.apps_dir(), "wiki": paths.wiki_dir()}
    expected = {"apps": tmp_path / "apps", "wiki": tmp_path / "xdg" / "callback" / "profile-wiki"}
    assert actual == expected


def test_write_text_atomic_creates_parents_and_leaves_no_temp_file(tmp_path: Path):
    target = tmp_path / "nested" / "file.txt"
    paths.write_text_atomic(target, "hello\n")
    actual = {
        "content": target.read_text(),
        "entries": sorted(p.name for p in target.parent.iterdir()),
    }
    expected = {"content": "hello\n", "entries": ["file.txt"]}
    assert actual == expected


def test_write_json_atomic_round_trips(tmp_path: Path):
    target = tmp_path / "data.json"
    paths.write_json_atomic(target, {"a": 1, "b": [1, 2]})
    actual = {
        "parsed": json.loads(target.read_text()),
        "entries": sorted(p.name for p in tmp_path.iterdir()),
    }
    expected = {"parsed": {"a": 1, "b": [1, 2]}, "entries": ["data.json"]}
    assert actual == expected
