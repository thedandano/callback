"""Tests for callback/settings.py: the env.json settings file callback owns."""

from __future__ import annotations

import logging
import sys

import pytest

from callback import paths, settings


@pytest.fixture(autouse=True)
def isolated_config_home(tmp_path, monkeypatch):
    """Point config_dir() at a scratch dir so a developer's real env.json never leaks in."""
    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path))
    monkeypatch.delenv("XDG_STATE_HOME", raising=False)
    monkeypatch.delenv("XDG_DATA_HOME", raising=False)
    return tmp_path


def test_read_env_file_returns_empty_dict_when_missing():
    assert settings.read_env_file() == {}


def test_read_env_file_raises_value_error_on_invalid_json():
    env_path = paths.env_file()
    env_path.parent.mkdir(parents=True, exist_ok=True)
    env_path.write_text("not json", encoding="utf-8")

    with pytest.raises(ValueError) as excinfo:
        settings.read_env_file()

    assert str(env_path) in str(excinfo.value)


def test_read_env_file_raises_value_error_on_non_string_value():
    env_path = paths.env_file()
    env_path.parent.mkdir(parents=True, exist_ok=True)
    env_path.write_text('{"FOO": 1}', encoding="utf-8")

    with pytest.raises(ValueError) as excinfo:
        settings.read_env_file()

    assert str(env_path) in str(excinfo.value)


def test_apply_env_file_sets_missing_key():
    paths.write_json_atomic(paths.env_file(), {"FOO": "bar"})
    environ: dict[str, str] = {}

    settings.apply_env_file(environ)

    assert environ == {"FOO": "bar"}


def test_apply_env_file_does_not_override_existing_process_env():
    paths.write_json_atomic(paths.env_file(), {"FOO": "bar"})
    environ = {"FOO": "existing"}

    settings.apply_env_file(environ)

    assert environ == {"FOO": "existing"}


def test_apply_env_file_logs_key_names_but_never_values(caplog):
    paths.write_json_atomic(paths.env_file(), {"LANGSMITH_API_KEY": "super-secret-value"})
    environ: dict[str, str] = {}

    with caplog.at_level(logging.INFO):
        settings.apply_env_file(environ)

    actual = {
        "has_key_name": any("LANGSMITH_API_KEY" in record.message for record in caplog.records),
        "leaks_value": any("super-secret-value" in record.message for record in caplog.records),
    }
    expected = {"has_key_name": True, "leaks_value": False}
    assert actual == expected


def test_apply_env_file_never_relocates_itself_via_xdg_config_home(caplog):
    """XDG_CONFIG_HOME is the bootstrap variable used to find env.json itself.

    Applying a value stored inside the file would make a later call to
    paths.env_file() resolve somewhere else than where this file was actually
    read from — splitting settings across two locations with no clear owner.
    """
    paths.write_json_atomic(
        paths.env_file(), {"XDG_CONFIG_HOME": "/should-be-ignored", "FOO": "bar"}
    )
    environ: dict[str, str] = {}

    with caplog.at_level(logging.WARNING):
        settings.apply_env_file(environ)

    actual = {
        "environ": environ,
        "warned": any(record.levelno == logging.WARNING for record in caplog.records),
    }
    expected = {"environ": {"FOO": "bar"}, "warned": True}
    assert actual == expected


def test_log_level_from_env_file_applies_before_server_module_reads_it(monkeypatch):
    """callback.server reads LOG_LEVEL into a module-level constant at import time.

    Settings must be loaded before that import happens (not deep inside run()), or a
    LOG_LEVEL set only in env.json is silently ignored for every server invocation.
    """
    monkeypatch.delenv("LOG_LEVEL", raising=False)
    paths.write_json_atomic(paths.env_file(), {"LOG_LEVEL": "DEBUG"})

    sys.modules.pop("callback.server", None)
    import callback.server

    assert callback.server.LOG_LEVEL == "DEBUG"
