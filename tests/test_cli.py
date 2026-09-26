"""Tests for the callback CLI."""

from __future__ import annotations

import json
import os
from pathlib import Path
from unittest.mock import ANY, MagicMock, Mock, patch

import pytest
from typer.testing import CliRunner

from callback import paths
from callback.cli import ConfigError, app

runner = CliRunner()


@pytest.fixture(autouse=True)
def _isolated_config_home(tmp_path, monkeypatch):
    """Keep the settings file inside tmp_path; a developer's real env.json must never leak in."""
    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path))


@pytest.fixture
def _isolated_host_configs(tmp_path, monkeypatch):
    """Point legacy Claude/Codex config paths at tmp_path so real host files are never touched."""
    claude_path = tmp_path / ".claude.json"
    codex_path = tmp_path / ".codex" / "config.toml"
    monkeypatch.setattr("callback.cli.DEFAULT_CLAUDE_CONFIG", claude_path)
    monkeypatch.setattr("callback.cli.DEFAULT_CODEX_CONFIG", codex_path)
    return claude_path, codex_path


def test_cli_help_lists_commands():
    result = runner.invoke(app, ["--help"])

    assert result.exit_code == 0
    commands = (
        "serve",
        "install-browsers",
        "uninstall",
        "update",
        "logs",
        "trace-check",
        "version",
        "config",
    )
    for command in commands:
        assert command in result.stdout
    assert "setup-mcp" not in result.stdout


def test_settings_load_before_any_command_runs():
    """env.json must be merged into os.environ before command logic executes.

    Path-resolving code (e.g. the server log path) reads os.environ directly, so a
    value set only in env.json is invisible unless settings load happens up front —
    not deep inside individual commands that happen to need it today.
    """
    marker = "CALLBACK_TEST_SETTINGS_LOAD_MARKER"
    os.environ.pop(marker, None)
    paths.write_json_atomic(paths.env_file(), {marker: "loaded"})

    try:
        result = runner.invoke(app, ["config", "status"])
        actual = {"exit_code": result.exit_code, "marker_value": os.environ.get(marker)}
        expected = {"exit_code": 0, "marker_value": "loaded"}
        assert actual == expected
    finally:
        os.environ.pop(marker, None)


def test_version_prints_installed_distribution_version(monkeypatch):
    monkeypatch.setattr("callback.cli._read_build_version", lambda: None)
    monkeypatch.setattr("callback.cli.importlib.metadata.version", lambda name: "0.1.0")

    result = runner.invoke(app, ["version"])

    assert result.exit_code == 0
    assert result.stdout.strip() == "0.1.0"


def test_version_prefers_generated_build_version(monkeypatch):
    monkeypatch.setattr("callback.cli._read_build_version", lambda: "0.3.0-01-abc1234")
    monkeypatch.setattr("callback.cli.importlib.metadata.version", lambda name: "0.3.0")

    result = runner.invoke(app, ["version"])

    assert result.exit_code == 0
    assert result.stdout.strip() == "0.3.0-01-abc1234"


def test_serve_uses_server_runner():
    run = Mock()

    with patch("callback.server.run", run):
        result = runner.invoke(app, ["serve"])

    assert result.exit_code == 0
    run.assert_called_once_with()


def test_serve_without_flags_uses_home_state_log(monkeypatch):
    run = Mock()
    configure_logging = Mock()
    startup_events: list[tuple[Path, str]] = []

    monkeypatch.delenv("CALLBACK_LOG_PATH", raising=False)

    def fake_write_startup_event(log_path: Path, line: str) -> None:
        startup_events.append((log_path, line))

    with (
        patch("callback.cli._write_startup_log_event", side_effect=fake_write_startup_event),
        patch("callback.server.configure_logging", configure_logging),
        patch("callback.server.run", run),
    ):
        result = runner.invoke(app, ["serve"])

    actual = {
        "exit_code": result.exit_code,
        "startup_log_path": startup_events[0][0],
    }
    expected = {
        "exit_code": 0,
        "startup_log_path": Path("~/.local/state/callback/server.log").expanduser(),
    }
    assert actual == expected
    configure_logging.assert_called_once_with(
        str(Path("~/.local/state/callback/server.log").expanduser())
    )
    run.assert_called_once_with()


def test_serve_respects_callback_log_path_already_set_by_settings(monkeypatch, tmp_path):
    """serve() must not clobber a CALLBACK_LOG_PATH the settings-loading callback
    already put in os.environ, when neither --log-path nor --project-logs was
    passed — otherwise env.json's override works for `python -m callback.server`
    but is silently ignored by the documented `callback serve` entry point."""
    configured_path = tmp_path / "from-settings" / "server.log"
    monkeypatch.setenv("CALLBACK_LOG_PATH", str(configured_path))
    startup_events: list[tuple[Path, str]] = []

    def fake_write_startup_event(log_path: Path, line: str) -> None:
        startup_events.append((log_path, line))

    with (
        patch("callback.cli._write_startup_log_event", side_effect=fake_write_startup_event),
        patch("callback.server.configure_logging", Mock()),
        patch("callback.server.run", Mock()),
    ):
        result = runner.invoke(app, ["serve"])

    actual = {"exit_code": result.exit_code, "startup_log_path": startup_events[0][0]}
    expected = {"exit_code": 0, "startup_log_path": configured_path}
    assert actual == expected


def test_malformed_settings_file_warns_instead_of_crashing_unrelated_commands():
    """A damaged env.json must not brick a command that never touches settings
    at all (uninstall doesn't read or write env.json) — every command
    dispatches through the same root callback that loads it."""
    env_path = paths.env_file()
    env_path.parent.mkdir(parents=True, exist_ok=True)
    env_path.write_text("not json", encoding="utf-8")

    with (
        patch("callback.cli._remove_server_from_claude"),
        patch("callback.cli._remove_server_from_codex"),
    ):
        result = runner.invoke(app, ["uninstall"])

    actual = {
        "exit_code": result.exit_code,
        "warns": "not valid JSON" in result.stderr,
    }
    expected = {"exit_code": 0, "warns": True}
    assert actual == expected


def test_serve_project_logs_uses_project_log(tmp_path, monkeypatch):
    run = Mock()
    configure_logging = Mock()
    startup_events: list[tuple[Path, str]] = []

    monkeypatch.delenv("CALLBACK_LOG_PATH", raising=False)
    monkeypatch.chdir(tmp_path)

    def fake_write_startup_event(log_path: Path, line: str) -> None:
        startup_events.append((log_path, line))

    with (
        patch("callback.cli._write_startup_log_event", side_effect=fake_write_startup_event),
        patch("callback.server.configure_logging", configure_logging),
        patch("callback.server.run", run),
    ):
        result = runner.invoke(app, ["serve", "--project-logs"], catch_exceptions=False)

    expected_log_path = tmp_path / ".callback" / "server.log"
    actual = {
        "exit_code": result.exit_code,
        "startup_log_path": startup_events[0][0],
    }
    expected = {"exit_code": 0, "startup_log_path": expected_log_path}
    assert actual == expected
    configure_logging.assert_called_once_with(str(expected_log_path))
    run.assert_called_once_with()


def test_serve_unwritable_log_path_still_runs(tmp_path):
    blocked_path = tmp_path / "blocked" / "server.log"
    run = Mock()

    with (
        patch("callback.cli._write_startup_log_event", side_effect=OSError("blocked")),
        patch("callback.server.configure_logging"),
        patch("callback.server.run", run),
    ):
        result = runner.invoke(app, ["serve", "--log-path", str(blocked_path)])

    assert result.exit_code == 0
    run.assert_called_once_with()


def test_logs_reports_missing_file(tmp_path):
    missing = tmp_path / "server.log"

    result = runner.invoke(app, ["logs", "--log-path", str(missing)])

    assert result.exit_code == 1
    assert f"Log file not found: {missing}" in result.stderr


def test_logs_prints_trailing_lines(tmp_path):
    log_path = tmp_path / "server.log"
    log_path.write_text("one\ntwo\nthree\n", encoding="utf-8")

    result = runner.invoke(app, ["logs", "--log-path", str(log_path), "--lines", "2"])

    assert result.exit_code == 0
    assert result.stdout.splitlines() == ["two", "three"]


def test_logs_defaults_to_home_state_log_even_when_project_log_exists(tmp_path, monkeypatch):
    state_log = tmp_path / "state" / "server.log"
    state_log.parent.mkdir()
    state_log.write_text("state\nstate-tail\n", encoding="utf-8")

    project_log = tmp_path / ".callback" / "server.log"
    project_log.parent.mkdir()
    project_log.write_text("project\nlog\n", encoding="utf-8")

    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr("callback.cli.DEFAULT_LOG_PATH", state_log)
    monkeypatch.delenv("CALLBACK_LOG_PATH", raising=False)

    result = runner.invoke(app, ["logs", "--lines", "1"])

    assert result.exit_code == 0
    assert result.stdout.splitlines() == ["state-tail"]


def test_logs_honors_callback_log_path_from_settings(tmp_path, monkeypatch):
    """`logs` must consult the same CALLBACK_LOG_PATH `serve` honors — otherwise
    `callback logs --follow` tails the wrong file (or reports one missing)
    whenever the configured path differs from the default.
    """
    configured_path = tmp_path / "configured" / "server.log"
    configured_path.parent.mkdir()
    configured_path.write_text("configured\nlog\n", encoding="utf-8")
    monkeypatch.setenv("CALLBACK_LOG_PATH", str(configured_path))

    result = runner.invoke(app, ["logs"])

    assert result.exit_code == 0
    assert result.stdout.splitlines() == ["configured", "log"]


def test_logs_project_logs_flag_uses_project_log(tmp_path, monkeypatch):
    project_log = tmp_path / ".callback" / "server.log"
    project_log.parent.mkdir()
    project_log.write_text("project\nlog\n", encoding="utf-8")

    monkeypatch.chdir(tmp_path)

    result = runner.invoke(app, ["logs", "--project-logs"])

    assert result.exit_code == 0
    assert result.stdout.splitlines() == ["project", "log"]


# ============================================================================
# config env set / unset / list
# ============================================================================


def test_config_env_set_list_unset_round_trips_through_settings_file():
    set_result = runner.invoke(app, ["config", "env", "set", "LANGSMITH_API_KEY", "secret-value"])

    actual = {
        "exit_code": set_result.exit_code,
        "env": json.loads(paths.env_file().read_text(encoding="utf-8")),
    }
    expected = {"exit_code": 0, "env": {"LANGSMITH_API_KEY": "secret-value"}}
    assert actual == expected

    list_result = runner.invoke(app, ["config", "env", "list"])
    actual = {
        "exit_code": list_result.exit_code,
        "redacted": "LANGSMITH_API_KEY=********" in list_result.stdout,
        "secret_hidden": "secret-value" not in list_result.stdout,
    }
    expected = {"exit_code": 0, "redacted": True, "secret_hidden": True}
    assert actual == expected

    show_result = runner.invoke(app, ["config", "env", "list", "--show-secrets"])
    actual = {
        "exit_code": show_result.exit_code,
        "secret_shown": "LANGSMITH_API_KEY=secret-value" in show_result.stdout,
    }
    expected = {"exit_code": 0, "secret_shown": True}
    assert actual == expected

    unset_result = runner.invoke(app, ["config", "env", "unset", "LANGSMITH_API_KEY"])
    actual = {
        "exit_code": unset_result.exit_code,
        "env": json.loads(paths.env_file().read_text(encoding="utf-8")),
    }
    expected = {"exit_code": 0, "env": {}}
    assert actual == expected


def test_config_env_set_preserves_other_existing_keys():
    paths.write_json_atomic(paths.env_file(), {"LANGSMITH_PROJECT": "Callback"})

    result = runner.invoke(app, ["config", "env", "set", "CALLBACK_TRACE_BACKEND", "langsmith"])

    actual = {
        "exit_code": result.exit_code,
        "env": json.loads(paths.env_file().read_text(encoding="utf-8")),
    }
    expected = {
        "exit_code": 0,
        "env": {"LANGSMITH_PROJECT": "Callback", "CALLBACK_TRACE_BACKEND": "langsmith"},
    }
    assert actual == expected

    unset_result = runner.invoke(app, ["config", "env", "unset", "CALLBACK_TRACE_BACKEND"])

    actual = {
        "exit_code": unset_result.exit_code,
        "env": json.loads(paths.env_file().read_text(encoding="utf-8")),
    }
    expected = {"exit_code": 0, "env": {"LANGSMITH_PROJECT": "Callback"}}
    assert actual == expected


def test_config_env_list_prints_flat_key_value_pairs_without_target_headers():
    paths.write_json_atomic(paths.env_file(), {"LANGSMITH_PROJECT": "Callback"})

    result = runner.invoke(app, ["config", "env", "list"])

    actual = {
        "exit_code": result.exit_code,
        "has_env": "LANGSMITH_PROJECT=Callback" in result.stdout,
        "no_target_header": "[claude]" not in result.stdout and "[codex]" not in result.stdout,
    }
    expected = {"exit_code": 0, "has_env": True, "no_target_header": True}
    assert actual == expected


def test_config_env_set_rejects_invalid_name_without_writing():
    result = runner.invoke(app, ["config", "env", "set", "bad-name", "value"])

    actual = {
        "exit_code": result.exit_code,
        "invalid_name_error": "invalid env var name" in result.stderr,
        "env_file_exists": paths.env_file().exists(),
    }
    expected = {"exit_code": 1, "invalid_name_error": True, "env_file_exists": False}
    assert actual == expected


# ============================================================================
# config langsmith
# ============================================================================


def test_config_langsmith_sets_expected_env_in_settings_file():
    result = runner.invoke(
        app,
        ["config", "langsmith", "--api-key", "lsv2-key", "--project", "callback-demo"],
    )

    expected_env = {
        "CALLBACK_TRACE_BACKEND": "langsmith",
        "LANGSMITH_TRACING": "true",
        "LANGSMITH_API_KEY": "lsv2-key",
        "LANGSMITH_ENDPOINT": "https://api.smith.langchain.com",
        "LANGSMITH_PROJECT": "callback-demo",
    }
    actual = {
        "exit_code": result.exit_code,
        "env": json.loads(paths.env_file().read_text(encoding="utf-8")),
    }
    expected = {"exit_code": 0, "env": expected_env}
    assert actual == expected


def test_config_langsmith_defaults_to_callback_project_and_langsmith_endpoint():
    result = runner.invoke(app, ["config", "langsmith", "--api-key", "lsv2-key"])

    actual = {
        "exit_code": result.exit_code,
        "env": json.loads(paths.env_file().read_text(encoding="utf-8")),
    }
    expected = {
        "exit_code": 0,
        "env": {
            "CALLBACK_TRACE_BACKEND": "langsmith",
            "LANGSMITH_TRACING": "true",
            "LANGSMITH_API_KEY": "lsv2-key",
            "LANGSMITH_ENDPOINT": "https://api.smith.langchain.com",
            "LANGSMITH_PROJECT": "Callback",
        },
    }
    assert actual == expected


# ============================================================================
# config status
# ============================================================================


def test_config_status_does_not_warn_about_comments(_isolated_host_configs):
    _claude_path, codex_path = _isolated_host_configs
    codex_path.parent.mkdir(parents=True, exist_ok=True)
    codex_path.write_text(
        '# my notes\n[mcp_servers.callback]\ncommand = "callback"\n', encoding="utf-8"
    )

    result = runner.invoke(app, ["config", "status"])

    actual = {"exit_code": result.exit_code, "warned_comments": "comments" in result.stderr}
    expected = {"exit_code": 0, "warned_comments": False}
    assert actual == expected


def test_config_status_reports_settings_redacting_secrets(_isolated_host_configs):
    paths.write_json_atomic(
        paths.env_file(),
        {
            "CALLBACK_TRACE_BACKEND": "langsmith",
            "LANGSMITH_TRACING": "true",
            "LANGSMITH_API_KEY": "lsv2-secret",
        },
    )

    result = runner.invoke(app, ["config", "status"])

    actual = {
        "exit_code": result.exit_code,
        "has_backend": "CALLBACK_TRACE_BACKEND=langsmith" in result.stdout,
        "has_tracing": "LANGSMITH_TRACING=true" in result.stdout,
        "redacts_key": "LANGSMITH_API_KEY=********" in result.stdout,
        "secret_hidden": "lsv2-secret" not in result.stdout,
    }
    expected = {
        "exit_code": 0,
        "has_backend": True,
        "has_tracing": True,
        "redacts_key": True,
        "secret_hidden": True,
    }
    assert actual == expected


def test_config_status_warns_about_legacy_entry_for_claude_only(_isolated_host_configs):
    claude_path, codex_path = _isolated_host_configs
    claude_path.write_text(
        json.dumps({"mcpServers": {"callback": {"command": "callback", "args": ["serve"]}}}),
        encoding="utf-8",
    )

    result = runner.invoke(app, ["config", "status"])

    actual = {
        "exit_code": result.exit_code,
        "warns_claude": str(claude_path) in result.stderr,
        "warns_codex": str(codex_path) in result.stderr,
    }
    expected = {"exit_code": 0, "warns_claude": True, "warns_codex": False}
    assert actual == expected


def test_config_status_show_secrets_reveals_secret_values(_isolated_host_configs):
    paths.write_json_atomic(paths.env_file(), {"LANGSMITH_API_KEY": "lsv2-secret"})

    result = runner.invoke(app, ["config", "status", "--show-secrets"])

    actual = {
        "exit_code": result.exit_code,
        "shows_secret": "LANGSMITH_API_KEY=lsv2-secret" in result.stdout,
    }
    expected = {"exit_code": 0, "shows_secret": True}
    assert actual == expected


def test_config_status_does_not_modify_legacy_host_configs(_isolated_host_configs):
    claude_path, codex_path = _isolated_host_configs
    claude_content = json.dumps({"mcpServers": {"callback": {"command": "callback"}}})
    claude_path.write_text(claude_content, encoding="utf-8")
    codex_path.parent.mkdir(parents=True, exist_ok=True)
    codex_content = '[mcp_servers.callback]\ncommand = "callback"\n'
    codex_path.write_text(codex_content, encoding="utf-8")

    result = runner.invoke(app, ["config", "status"])

    actual = {
        "exit_code": result.exit_code,
        "claude_unchanged": claude_path.read_text(encoding="utf-8") == claude_content,
        "codex_unchanged": codex_path.read_text(encoding="utf-8") == codex_content,
    }
    expected = {"exit_code": 0, "claude_unchanged": True, "codex_unchanged": True}
    assert actual == expected


def test_config_status_missing_settings_file_reports_none_without_writing(_isolated_host_configs):
    result = runner.invoke(app, ["config", "status"])

    actual = {
        "exit_code": result.exit_code,
        "has_none": "(none)" in result.stdout,
        "env_file_exists": paths.env_file().exists(),
    }
    expected = {"exit_code": 0, "has_none": True, "env_file_exists": False}
    assert actual == expected


def test_config_status_hedges_on_legacy_entry_instead_of_assuming_duplicate(
    _isolated_host_configs,
):
    """A presence-only check can't tell a leftover duplicate from someone's only,
    correctly-configured manual registration — so the message must not confidently
    tell every reader to delete their one working entry."""
    claude_path, _codex_path = _isolated_host_configs
    claude_path.write_text(
        json.dumps({"mcpServers": {"callback": {"command": "callback", "args": ["serve"]}}}),
        encoding="utf-8",
    )

    result = runner.invoke(app, ["config", "status"])

    actual = {
        "exit_code": result.exit_code,
        "mentions_uninstall": "callback uninstall" in result.stderr,
        "hedges_for_sole_install": "only callback registration" in result.stderr,
        "asserts_duplicate_as_fact": "legacy duplicate server" in result.stderr,
    }
    expected = {
        "exit_code": 0,
        "mentions_uninstall": True,
        "hedges_for_sole_install": True,
        "asserts_duplicate_as_fact": False,
    }
    assert actual == expected


def test_config_status_survives_malformed_legacy_host_config(_isolated_host_configs):
    """A malformed legacy host config must not hide an otherwise-valid settings file."""
    claude_path, _codex_path = _isolated_host_configs
    claude_path.write_text("not valid json", encoding="utf-8")
    paths.write_json_atomic(paths.env_file(), {"FOO": "bar"})

    result = runner.invoke(app, ["config", "status"])

    actual = {
        "exit_code": result.exit_code,
        "reports_settings": "FOO=bar" in result.stdout,
        "warns_about_claude_probe": str(claude_path) in result.stderr,
    }
    expected = {"exit_code": 0, "reports_settings": True, "warns_about_claude_probe": True}
    assert actual == expected


def test_config_status_survives_unreadable_legacy_host_config(_isolated_host_configs):
    """A filesystem-level read failure on a legacy host config (e.g. it's
    accidentally a directory) must not hide an otherwise-valid settings file
    either — same as the malformed-JSON case above, but for OSError."""
    claude_path, _codex_path = _isolated_host_configs
    claude_path.mkdir()  # a directory at the config path, not a file
    paths.write_json_atomic(paths.env_file(), {"FOO": "bar"})

    result = runner.invoke(app, ["config", "status"])

    actual = {
        "exit_code": result.exit_code,
        "reports_settings": "FOO=bar" in result.stdout,
        "warns_about_claude_probe": str(claude_path) in result.stderr,
    }
    expected = {"exit_code": 0, "reports_settings": True, "warns_about_claude_probe": True}
    assert actual == expected


def test_config_langsmith_and_env_set_never_touch_host_config_files(_isolated_host_configs):
    claude_path, codex_path = _isolated_host_configs
    claude_content = json.dumps({"mcpServers": {"other": {"command": "other"}}})
    claude_path.write_text(claude_content, encoding="utf-8")
    codex_path.parent.mkdir(parents=True, exist_ok=True)
    codex_content = '[mcp_servers.other]\ncommand = "other"\n'
    codex_path.write_text(codex_content, encoding="utf-8")

    runner.invoke(app, ["config", "langsmith", "--api-key", "lsv2-key"])
    runner.invoke(app, ["config", "env", "set", "FOO", "bar"])

    actual = {
        "claude_unchanged": claude_path.read_text(encoding="utf-8") == claude_content,
        "codex_unchanged": codex_path.read_text(encoding="utf-8") == codex_content,
    }
    expected = {"claude_unchanged": True, "codex_unchanged": True}
    assert actual == expected


# ============================================================================
# trace-check
# ============================================================================


def test_trace_check_reports_missing_langsmith_key(monkeypatch):
    monkeypatch.setenv("CALLBACK_TRACE_BACKEND", "langsmith")
    monkeypatch.setenv("LANGSMITH_TRACING", "true")
    monkeypatch.delenv("LANGSMITH_API_KEY", raising=False)

    result = runner.invoke(app, ["trace-check"])

    assert result.exit_code == 1
    assert "LANGSMITH_API_KEY is required" in result.stderr


def test_trace_check_reads_settings_file_and_emits_safe_trace(monkeypatch):
    monkeypatch.delenv("CALLBACK_TRACE_BACKEND", raising=False)
    monkeypatch.delenv("LANGSMITH_TRACING", raising=False)
    monkeypatch.delenv("LANGSMITH_API_KEY", raising=False)
    monkeypatch.delenv("LANGSMITH_PROJECT", raising=False)
    paths.write_json_atomic(
        paths.env_file(),
        {
            "CALLBACK_TRACE_BACKEND": "langsmith",
            "LANGSMITH_TRACING": "true",
            "LANGSMITH_API_KEY": "lsv2-secret",
            "LANGSMITH_PROJECT": "callback-demo",
        },
    )

    class FakeClient:
        def list_projects(self, limit: int):
            assert limit == 1
            return iter([object()])

    with (
        patch("callback.cli._make_langsmith_client", return_value=FakeClient()) as make_client,
        patch("callback.cli.emit_trace_check_probe") as emit_trace,
    ):
        result = runner.invoke(app, ["trace-check", "--emit-test-trace"])

    actual = {
        "exit_code": result.exit_code,
        "reports_ok": "ok" in result.stdout,
        "secret_hidden": "lsv2-secret" not in result.stdout,
    }
    expected = {"exit_code": 0, "reports_ok": True, "secret_hidden": True}
    assert actual == expected
    make_client.assert_called_once()
    emit_trace.assert_called_once()


def test_trace_check_redacts_secret_on_auth_failure(monkeypatch):
    monkeypatch.setenv("CALLBACK_TRACE_BACKEND", "langsmith")
    monkeypatch.setenv("LANGSMITH_TRACING", "true")
    monkeypatch.setenv("LANGSMITH_API_KEY", "lsv2-secret")

    class FakeClient:
        def list_projects(self, limit: int):
            raise RuntimeError("bad token lsv2-secret")

    with patch("callback.cli._make_langsmith_client", return_value=FakeClient()):
        result = runner.invoke(app, ["trace-check"])

    assert result.exit_code == 1
    assert "bad token" in result.stderr
    assert "lsv2-secret" not in result.stderr


# ============================================================================
# install-browsers, uninstall, update
# ============================================================================


def test_install_browsers_calls_playwright():
    mock_result = MagicMock()
    mock_result.returncode = 0

    with patch("callback.cli.subprocess.run", return_value=mock_result) as mock_run:
        result = runner.invoke(app, ["install-browsers"])

    import sys

    mock_run.assert_called_once_with([sys.executable, "-m", "playwright", "install", "chromium"])
    assert result.exit_code == 0


def test_uninstall_removes_claude_entry(tmp_path):
    from callback.cli import _remove_server_from_claude

    claude_path = tmp_path / ".claude.json"
    entry = {"command": "callback", "args": ["serve"]}
    existing = {"theme": "dark", "mcpServers": {"callback": entry}}
    claude_path.write_text(json.dumps(existing), encoding="utf-8")

    _remove_server_from_claude(claude_path)

    config = json.loads(claude_path.read_text(encoding="utf-8"))
    assert config == {"theme": "dark", "mcpServers": {}}


def test_uninstall_skips_missing_config_files(tmp_path):
    from callback.cli import _remove_server_from_claude, _remove_server_from_codex

    missing_claude = tmp_path / ".claude.json"
    missing_codex = tmp_path / "config.toml"

    _remove_server_from_claude(missing_claude)
    _remove_server_from_codex(missing_codex)

    assert not missing_claude.exists()
    assert not missing_codex.exists()


def test_uninstall_without_purge_preserves_data_dir(tmp_path):
    data_dir = tmp_path / "callback-data"
    data_dir.mkdir()

    state_dir = tmp_path / "state"
    with (
        patch("callback.paths.data_dir", lambda: data_dir),
        patch("callback.paths.state_dir", lambda: state_dir),
        patch("callback.cli._remove_server_from_claude"),
        patch("callback.cli._remove_server_from_codex"),
    ):
        result = runner.invoke(app, ["uninstall"])

    assert result.exit_code == 0
    assert data_dir.exists()


def test_uninstall_purge_deletes_data_state_and_config_dirs(tmp_path):
    data_dir = tmp_path / "share"
    state_dir = tmp_path / "state"
    config_dir = tmp_path / "config"
    data_dir.mkdir()
    state_dir.mkdir()
    config_dir.mkdir()

    with (
        patch("callback.paths.data_dir", lambda: data_dir),
        patch("callback.paths.state_dir", lambda: state_dir),
        patch("callback.paths.config_dir", lambda: config_dir),
        patch("callback.cli._remove_server_from_claude"),
        patch("callback.cli._remove_server_from_codex"),
    ):
        result = runner.invoke(app, ["uninstall", "--purge"])

    assert result.exit_code == 0
    assert not data_dir.exists()
    assert not state_dir.exists()
    assert not config_dir.exists()


def test_uninstall_purge_deletes_data_when_legacy_config_removal_fails(tmp_path):
    data_dir = tmp_path / "share"
    state_dir = tmp_path / "state"
    config_dir = tmp_path / "config"
    data_dir.mkdir()
    state_dir.mkdir()
    config_dir.mkdir()

    with (
        patch("callback.paths.data_dir", lambda: data_dir),
        patch("callback.paths.state_dir", lambda: state_dir),
        patch("callback.paths.config_dir", lambda: config_dir),
        patch(
            "callback.cli._remove_server_from_claude",
            side_effect=ConfigError("invalid Claude config"),
        ),
    ):
        result = runner.invoke(app, ["uninstall", "--purge"])

    assert result.exit_code == 1
    assert "uninstall failed: invalid Claude config" in result.stderr
    assert not data_dir.exists()
    assert not state_dir.exists()
    assert not config_dir.exists()


def test_uninstall_purge_skips_absent_dirs(tmp_path):
    data_dir = tmp_path / "share"
    state_dir = tmp_path / "state"
    config_dir = tmp_path / "config"

    with (
        patch("callback.paths.data_dir", lambda: data_dir),
        patch("callback.paths.state_dir", lambda: state_dir),
        patch("callback.paths.config_dir", lambda: config_dir),
        patch("callback.cli._remove_server_from_claude"),
        patch("callback.cli._remove_server_from_codex"),
    ):
        invoke_result = runner.invoke(app, ["uninstall", "--purge"])

    assert invoke_result.exit_code == 0


def test_update_calls_uv_tool_upgrade():
    mock_result = MagicMock()
    mock_result.returncode = 0

    with patch("callback.cli.subprocess.run", return_value=mock_result) as mock_run:
        result = runner.invoke(app, ["update"])

    mock_run.assert_called_once_with(["uv", "tool", "upgrade", "callback"])
    assert result.exit_code == 0


# ============================================================================
# setup-plugin
# ============================================================================


def test_setup_plugin_print_only_claude_prints_commands_no_browsers():
    fake_commands = [
        "claude plugin marketplace add thedandano/callback",
        "claude plugin install callback@callback",
    ]

    with (
        patch("callback.cli.install", return_value=fake_commands) as mock_install,
        patch("callback.cli._install_browsers") as mock_browsers,
    ):
        result = runner.invoke(
            app,
            ["setup-plugin", "--print-only", "--target", "claude"],
            catch_exceptions=False,
        )

    assert result.exit_code == 0
    mock_browsers.assert_not_called()
    mock_install.assert_called_once_with(ANY, source=None, print_only=True)
    assert "Would run:" in result.stdout
    assert fake_commands[0] in result.stdout
    assert fake_commands[1] in result.stdout
    assert "reload-plugins" in result.stdout or "restart" in result.stdout


def test_setup_plugin_print_only_both_prints_claude_then_codex():
    fake_commands = [
        "claude plugin marketplace add thedandano/callback",
        "claude plugin install callback@callback",
        "codex plugin marketplace add thedandano/callback",
        "codex plugin add callback@callback",
    ]

    with (
        patch("callback.cli.install", return_value=fake_commands) as mock_install,
        patch("callback.cli._install_browsers"),
    ):
        result = runner.invoke(
            app,
            ["setup-plugin", "--print-only", "--target", "both"],
            catch_exceptions=False,
        )

    assert result.exit_code == 0
    mock_install.assert_called_once_with(ANY, source=None, print_only=True)
    output = result.stdout
    idx_claude_mp = output.index(fake_commands[0])
    idx_claude_in = output.index(fake_commands[1])
    idx_codex_mp = output.index(fake_commands[2])
    idx_codex_in = output.index(fake_commands[3])
    assert idx_claude_mp < idx_claude_in < idx_codex_mp < idx_codex_in
    assert "Would run:" in output


def test_setup_plugin_invalid_target_exits_nonzero():
    result = runner.invoke(
        app,
        ["setup-plugin", "--target", "zzz"],
    )

    assert result.exit_code != 0


def test_setup_plugin_default_run_calls_install_and_browsers():
    fake_commands = [
        "claude plugin marketplace add thedandano/callback",
        "claude plugin install callback@callback",
        "codex plugin marketplace add thedandano/callback",
        "codex plugin add callback@callback",
    ]

    with (
        patch("callback.cli.install", return_value=fake_commands) as mock_install,
        patch("callback.cli._install_browsers", return_value=0) as mock_browsers,
    ):
        result = runner.invoke(
            app,
            ["setup-plugin"],
            catch_exceptions=False,
        )

    assert result.exit_code == 0
    mock_browsers.assert_called_once()
    mock_install.assert_called_once_with(ANY, source=None, print_only=False)
    assert "Ran:" in result.stdout
    for cmd in fake_commands:
        assert cmd in result.stdout


def test_setup_plugin_skip_browsers_does_not_call_install_browsers():
    fake_commands = [
        "claude plugin marketplace add thedandano/callback",
        "claude plugin install callback@callback",
    ]

    with (
        patch("callback.cli.install", return_value=fake_commands),
        patch("callback.cli._install_browsers") as mock_browsers,
    ):
        result = runner.invoke(
            app,
            ["setup-plugin", "--skip-browsers", "--target", "claude"],
            catch_exceptions=False,
        )

    assert result.exit_code == 0
    mock_browsers.assert_not_called()


def test_setup_plugin_plugin_source_override_passes_resolved_path(tmp_path):
    """--plugin-source resolves the local path and passes it as source."""
    local_path = tmp_path / "myrepo"
    local_path.mkdir()
    fake_commands = [
        f"claude plugin marketplace add {local_path}",
        "claude plugin install callback@callback",
    ]

    with (
        patch("callback.cli.install", return_value=fake_commands) as mock_install,
        patch("callback.cli._install_browsers"),
    ):
        result = runner.invoke(
            app,
            [
                "setup-plugin",
                "--print-only",
                "--target",
                "claude",
                "--plugin-source",
                str(local_path),
            ],
            catch_exceptions=False,
        )

    assert result.exit_code == 0
    mock_install.assert_called_once_with(ANY, source=str(local_path), print_only=True)


def test_setup_plugin_plugin_install_error_exits_nonzero():
    from callback.plugin_install import PluginInstallError

    with (
        patch("callback.cli.install", side_effect=PluginInstallError("runner failed")),
        patch("callback.cli._install_browsers", return_value=0),
    ):
        result = runner.invoke(
            app,
            ["setup-plugin"],
        )

    assert result.exit_code != 0
    assert "runner failed" in result.stderr
