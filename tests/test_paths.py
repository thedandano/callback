import json
import logging
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
        "apply_db": paths.apply_db_path(),
        "profile_db": paths.profile_db_path(),
        "state": paths.state_dir(),
    }
    data_root = tmp_path / ".local" / "share" / "callback"
    state_root = tmp_path / ".local" / "state" / "callback"
    expected = {
        "data": data_root,
        "inputs": data_root / "inputs",
        "wiki": data_root / "profile-wiki",
        "apps": data_root / "applications",
        "apply_db": state_root / "apply-sessions.db",
        "profile_db": state_root / "profile-sessions.db",
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


def test_apply_db_path_is_under_state_dir(monkeypatch, tmp_path: Path):
    monkeypatch.setenv("XDG_STATE_HOME", str(tmp_path))
    monkeypatch.delenv("XDG_DATA_HOME", raising=False)
    assert paths.apply_db_path().parent == paths.state_dir()


def test_profile_db_path_is_under_state_dir(monkeypatch, tmp_path: Path):
    monkeypatch.setenv("XDG_STATE_HOME", str(tmp_path))
    monkeypatch.delenv("XDG_DATA_HOME", raising=False)
    assert paths.profile_db_path().parent == paths.state_dir()


def test_log_path_is_under_state_dir(monkeypatch, tmp_path: Path):
    monkeypatch.setenv("XDG_STATE_HOME", str(tmp_path))
    monkeypatch.delenv("XDG_DATA_HOME", raising=False)
    assert paths.log_path() == paths.state_dir() / "server.log"


def test_move_legacy_file_moves_existing_file(tmp_path: Path):
    legacy = tmp_path / "legacy" / "apply-sessions.db"
    legacy.parent.mkdir(parents=True)
    legacy.write_text("legacy-db")
    target = tmp_path / "state" / "apply-sessions.db"

    paths.move_legacy_file(legacy, target)

    actual = {
        "target_exists": target.exists(),
        "legacy_exists": legacy.exists(),
        "content": target.read_text(),
    }
    expected = {"target_exists": True, "legacy_exists": False, "content": "legacy-db"}
    assert actual == expected


def test_move_legacy_file_moves_wal_shm_siblings(tmp_path: Path):
    legacy = tmp_path / "legacy" / "apply-sessions.db"
    legacy.parent.mkdir(parents=True)
    legacy.write_text("legacy-db")
    legacy_wal = Path(f"{legacy}-wal")
    legacy_shm = Path(f"{legacy}-shm")
    legacy_wal.write_text("wal")
    legacy_shm.write_text("shm")
    target = tmp_path / "state" / "apply-sessions.db"

    paths.move_legacy_file(legacy, target)

    actual = {
        "target_db_exists": target.exists(),
        "target_wal_exists": Path(f"{target}-wal").exists(),
        "target_shm_exists": Path(f"{target}-shm").exists(),
        "legacy_wal_exists": legacy_wal.exists(),
        "legacy_shm_exists": legacy_shm.exists(),
    }
    expected = {
        "target_db_exists": True,
        "target_wal_exists": True,
        "target_shm_exists": True,
        "legacy_wal_exists": False,
        "legacy_shm_exists": False,
    }
    assert actual == expected


def test_move_legacy_file_moves_wal_and_shm_before_the_main_file(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
):
    """The main .db file must move last.

    If the process is interrupted (or the move is non-atomic across filesystems),
    an interruption must always leave the ORIGINAL main file still at the legacy
    path — never a main file at target whose WAL never made the trip, which would
    silently roll back or lose uncommitted sessions on the next open.
    """
    legacy = tmp_path / "legacy" / "apply-sessions.db"
    legacy.parent.mkdir(parents=True)
    legacy.write_text("legacy-db")
    Path(f"{legacy}-wal").write_text("wal")
    Path(f"{legacy}-shm").write_text("shm")
    target = tmp_path / "state" / "apply-sessions.db"

    moved_order: list[str] = []
    real_move = paths.shutil.move

    def _tracking_move(src: str, dst: str) -> str:
        moved_order.append(Path(src).name)
        return real_move(src, dst)

    monkeypatch.setattr(paths.shutil, "move", _tracking_move)

    paths.move_legacy_file(legacy, target)

    assert moved_order == [
        "apply-sessions.db-wal",
        "apply-sessions.db-shm",
        "apply-sessions.db",
    ]


def test_move_legacy_file_never_leaves_a_partial_file_at_the_final_name(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
):
    """Cross-filesystem shutil.move copies then unlinks — not atomic. If the copy
    is interrupted partway, a truncated file can land at the destination name.
    That must never be the real target name: only a retry-safe staging name,
    so target.exists() never means "half a database."
    """
    legacy = tmp_path / "legacy" / "apply-sessions.db"
    legacy.parent.mkdir(parents=True)
    legacy.write_text("legacy-db-full-content")
    target = tmp_path / "state" / "apply-sessions.db"

    def _interrupted_move(src: str, dst: str) -> None:
        Path(dst).parent.mkdir(parents=True, exist_ok=True)
        Path(dst).write_text("truncated")
        raise OSError("simulated interruption mid-copy")

    monkeypatch.setattr(paths.shutil, "move", _interrupted_move)

    with pytest.raises(OSError):
        paths.move_legacy_file(legacy, target)

    assert target.exists() is False


def test_move_legacy_file_noop_when_legacy_missing(tmp_path: Path):
    legacy = tmp_path / "legacy" / "apply-sessions.db"
    target = tmp_path / "state" / "apply-sessions.db"

    paths.move_legacy_file(legacy, target)

    assert target.exists() is False


def test_move_legacy_file_leaves_legacy_when_both_exist(tmp_path: Path, caplog):
    legacy = tmp_path / "legacy" / "apply-sessions.db"
    legacy.parent.mkdir(parents=True)
    legacy.write_text("legacy-content")
    target = tmp_path / "state" / "apply-sessions.db"
    target.parent.mkdir(parents=True)
    target.write_text("target-content")

    with caplog.at_level(logging.WARNING):
        paths.move_legacy_file(legacy, target)

    actual = {
        "target_content": target.read_text(),
        "legacy_exists": legacy.exists(),
        "warning_logged": any(record.levelno == logging.WARNING for record in caplog.records),
    }
    expected = {"target_content": "target-content", "legacy_exists": True, "warning_logged": True}
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
