import json
from pathlib import Path
from typing import Any

import pytest

from callback.repositories.atomic import write_json_atomic, write_text_atomic


def test_write_text_atomic_creates_parents_and_leaves_no_temp_file(tmp_path: Path):
    target = tmp_path / "nested" / "file.txt"
    write_text_atomic(target, "hello\n")
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
        write_text_atomic(target, bad_content)
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
    write_json_atomic(target, {"a": 1, "b": [1, 2]})
    actual = {
        "parsed": json.loads(target.read_text()),
        "entries": sorted(p.name for p in tmp_path.iterdir()),
    }
    expected = {"parsed": {"a": 1, "b": [1, 2]}, "entries": ["data.json"]}
    assert actual == expected


def test_write_text_atomic_cleans_up_temp_file_on_rename_failure(tmp_path: Path, monkeypatch):
    target = tmp_path / "file.txt"

    def boom(self: Path, _target: Path) -> Path:
        raise OSError("rename refused")

    monkeypatch.setattr(Path, "replace", boom)
    raised = None
    try:
        write_text_atomic(target, "hello\n")
    except OSError as exc:
        raised = str(exc)
    actual = {"raised": raised, "entries": sorted(p.name for p in tmp_path.iterdir())}
    expected = {"raised": "rename refused", "entries": []}
    assert actual == expected
