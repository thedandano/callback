import json
import os
from pathlib import Path
from typing import Any

import pytest

from callback import paths


def test_data_dir_defaults_under_home(monkeypatch, tmp_path: Path):
    monkeypatch.delenv("XDG_DATA_HOME", raising=False)
    monkeypatch.delenv("XDG_STATE_HOME", raising=False)
    monkeypatch.setattr(Path, "home", staticmethod(lambda: tmp_path))
    actual = {
        "data": paths.data_dir(),
        "inputs": paths.inputs_dir(),
        "wiki": paths.wiki_dir(),
        "apps": paths.apps_dir(),
        "state": paths.state_dir(),
    }
    data_root = tmp_path / ".local" / "share" / "callback"
    state_root = tmp_path / ".local" / "state" / "callback"
    expected = {
        "data": data_root,
        "inputs": data_root / "inputs",
        "wiki": data_root / "profile-wiki",
        "apps": data_root / "applications",
        "state": state_root,
    }
    assert actual == expected


def test_xdg_data_home_moves_every_data_path(monkeypatch, tmp_path: Path):
    monkeypatch.setenv("XDG_DATA_HOME", str(tmp_path / "xdg"))
    monkeypatch.delenv("CALLBACK_APPS_DIR", raising=False)
    monkeypatch.delenv("XDG_STATE_HOME", raising=False)
    actual = {
        "data": paths.data_dir(),
        "inputs": paths.inputs_dir(),
        "wiki": paths.wiki_dir(),
        "apps": paths.apps_dir(),
    }
    root = tmp_path / "xdg" / "callback"
    expected = {
        "data": root,
        "inputs": root / "inputs",
        "wiki": root / "profile-wiki",
        "apps": root / "applications",
    }
    assert actual == expected
    # apply_db_path()/profile_db_path() now live under state_dir(), which is governed
    # by XDG_STATE_HOME (not XDG_DATA_HOME) — see the XDG_STATE_HOME tests below,
    # so changing XDG_DATA_HOME alone must not move them.


def test_callback_apps_dir_overrides_only_the_archive(monkeypatch, tmp_path: Path):
    monkeypatch.setenv("XDG_DATA_HOME", str(tmp_path / "xdg"))
    monkeypatch.setenv("CALLBACK_APPS_DIR", str(tmp_path / "apps"))
    monkeypatch.delenv("XDG_STATE_HOME", raising=False)
    actual = {"apps": paths.apps_dir(), "wiki": paths.wiki_dir()}
    expected = {"apps": tmp_path / "apps", "wiki": tmp_path / "xdg" / "callback" / "profile-wiki"}
    assert actual == expected


def test_state_dir_honors_xdg_state_home(monkeypatch, tmp_path: Path):
    monkeypatch.setenv("XDG_STATE_HOME", str(tmp_path))
    monkeypatch.delenv("XDG_DATA_HOME", raising=False)
    assert paths.state_dir() == tmp_path / "callback"


def test_state_dir_defaults_under_home_local_state(monkeypatch, tmp_path: Path):
    monkeypatch.delenv("XDG_STATE_HOME", raising=False)
    monkeypatch.delenv("XDG_DATA_HOME", raising=False)
    monkeypatch.setattr(Path, "home", staticmethod(lambda: tmp_path))
    assert paths.state_dir() == tmp_path / ".local" / "state" / "callback"


def test_state_dir_ignores_a_relative_xdg_state_home(monkeypatch, tmp_path: Path):
    """The XDG spec requires these paths to be absolute and treats a relative
    value as invalid — different processes with different cwds would
    otherwise silently land on different session stores."""
    monkeypatch.setenv("XDG_STATE_HOME", "relative/path")
    monkeypatch.setattr(Path, "home", staticmethod(lambda: tmp_path))
    assert paths.state_dir() == tmp_path / ".local" / "state" / "callback"


def test_data_dir_ignores_a_relative_xdg_data_home(monkeypatch, tmp_path: Path):
    monkeypatch.setenv("XDG_DATA_HOME", "relative/path")
    monkeypatch.setattr(Path, "home", staticmethod(lambda: tmp_path))
    assert paths.data_dir() == tmp_path / ".local" / "share" / "callback"


def test_config_dir_ignores_a_relative_xdg_config_home(monkeypatch, tmp_path: Path):
    monkeypatch.setenv("XDG_CONFIG_HOME", "relative/path")
    monkeypatch.setattr(Path, "home", staticmethod(lambda: tmp_path))
    assert paths.config_dir() == tmp_path / ".config" / "callback"


def test_session_dbs_live_in_the_session_dir(tmp_path: Path):
    actual = (paths.session_dir(), paths.apply_db_path(), paths.profile_db_path())
    name = f"callback-{os.getuid()}" if hasattr(os, "getuid") else "callback"
    folder = tmp_path / "tmp" / name
    expected = (folder, folder / "apply-sessions.db", folder / "profile-sessions.db")
    assert actual == expected


def test_log_path_is_under_state_dir(monkeypatch, tmp_path: Path):
    monkeypatch.setenv("XDG_STATE_HOME", str(tmp_path))
    monkeypatch.delenv("XDG_DATA_HOME", raising=False)
    assert paths.log_path() == paths.state_dir() / "server.log"


def test_write_text_atomic_creates_parents_and_leaves_no_temp_file(tmp_path: Path):
    target = tmp_path / "nested" / "file.txt"
    paths.write_text_atomic(target, "hello\n")
    actual = {
        "content": target.read_text(),
        "entries": sorted(p.name for p in target.parent.iterdir()),
    }
    expected = {"content": "hello\n", "entries": ["file.txt"]}
    assert actual == expected


def test_write_text_atomic_cleans_up_temp_file_on_write_failure(tmp_path: Path):
    target = tmp_path / "nested" / "file.txt"
    bad_content: Any = 42
    with pytest.raises(TypeError):
        paths.write_text_atomic(target, bad_content)
    actual = {
        "target_exists": target.exists(),
        "leftover_entries": (
            sorted(p.name for p in target.parent.iterdir()) if target.parent.exists() else []
        ),
    }
    expected = {"target_exists": False, "leftover_entries": []}
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


def test_config_dir_defaults_under_home(monkeypatch, tmp_path: Path):
    monkeypatch.delenv("XDG_CONFIG_HOME", raising=False)
    monkeypatch.setattr(Path, "home", staticmethod(lambda: tmp_path))
    actual = {
        "config": paths.config_dir(),
        "env_file": paths.env_file(),
    }
    root = tmp_path / ".config" / "callback"
    expected = {
        "config": root,
        "env_file": root / "env.json",
    }
    assert actual == expected


def test_xdg_config_home_moves_config_dir(monkeypatch, tmp_path: Path):
    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path / "xdg"))
    actual = {
        "config": paths.config_dir(),
        "env_file": paths.env_file(),
    }
    root = tmp_path / "xdg" / "callback"
    expected = {
        "config": root,
        "env_file": root / "env.json",
    }
    assert actual == expected


def test_write_text_atomic_cleans_up_temp_file_on_rename_failure(tmp_path: Path, monkeypatch):
    target = tmp_path / "file.txt"

    def boom(self: Path, _target: Path) -> Path:
        raise OSError("rename refused")

    monkeypatch.setattr(Path, "replace", boom)
    raised = None
    try:
        paths.write_text_atomic(target, "hello\n")
    except OSError as exc:
        raised = str(exc)
    actual = {"raised": raised, "entries": sorted(p.name for p in tmp_path.iterdir())}
    expected = {"raised": "rename refused", "entries": []}
    assert actual == expected


@pytest.mark.parametrize(
    ("parts", "expected"),
    [
        (("ExpertVoice", "Frontend AI Engineer"), "expertvoice-frontend-ai-engineer"),
        (("AT&T", "Sr. Engineer, Platform"), "at-t-sr-engineer-platform"),
        (("Acme", "Senior Engineer"), "acme-senior-engineer"),
        ((None, None), "job"),
    ],
)
def test_slug_matches_the_skill_folder_names(parts, expected):
    assert paths.slug(*parts) == expected


def test_slug_keeps_punctuation_and_non_ascii_roles_distinct():
    cpp = paths.slug("Acme", "C++ Engineer")
    csharp = paths.slug("Acme", "C# Engineer")
    non_ascii = paths.slug("Acme", "Ingénieur Logiciel")
    only_non_ascii = paths.slug("株式会社", "エンジニア")

    assert (cpp != csharp, non_ascii != "acme-ing-nieur-logiciel", only_non_ascii != "job") == (
        True,
        True,
        True,
    )
    assert paths.slug("Acme", "Ingénieur Logiciel") == non_ascii
    assert len(only_non_ascii) <= paths.SLUG_MAX_LENGTH


def test_slug_bounds_long_names_and_keeps_distinct_ones_distinct():
    first = paths.slug("Acme", "Senior Engineer " * 20 + "alpha")
    second = paths.slug("Acme", "Senior Engineer " * 20 + "beta")

    actual = (len(first) <= paths.SLUG_MAX_LENGTH, len(second) <= paths.SLUG_MAX_LENGTH)
    assert actual == (True, True)
    assert first != second


def test_ledger_lives_in_the_data_dir(monkeypatch, tmp_path: Path):
    monkeypatch.setattr(paths, "ledger_path", paths.__dict__["_ledger_path_impl"])
    monkeypatch.setenv("XDG_DATA_HOME", str(tmp_path))
    assert paths.ledger_path() == tmp_path / "callback" / "ledger.db"
