"""Tests for the callback CLI."""

from __future__ import annotations

import json
import tomllib
from pathlib import Path
from unittest.mock import ANY, MagicMock, Mock, patch

from typer.testing import CliRunner

from callback.cli import app, configure_claude, configure_codex

runner = CliRunner()


def _read_toml(path: Path) -> dict:
    with path.open("rb") as handle:
        return tomllib.load(handle)


def test_cli_help_lists_commands():
    result = runner.invoke(app, ["--help"])

    assert result.exit_code == 0
    commands = (
        "serve",
        "setup-mcp",
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

    result = runner.invoke(app, ["logs", "--lines", "1"])

    assert result.exit_code == 0
    assert result.stdout.splitlines() == ["state-tail"]


def test_logs_project_logs_flag_uses_project_log(tmp_path, monkeypatch):
    project_log = tmp_path / ".callback" / "server.log"
    project_log.parent.mkdir()
    project_log.write_text("project\nlog\n", encoding="utf-8")

    monkeypatch.chdir(tmp_path)

    result = runner.invoke(app, ["logs", "--project-logs"])

    assert result.exit_code == 0
    assert result.stdout.splitlines() == ["project", "log"]


def test_configure_claude_creates_entry_and_preserves_unrelated_keys(tmp_path):
    config_path = tmp_path / ".claude.json"
    config_path.write_text(json.dumps({"theme": "dark"}), encoding="utf-8")

    configure_claude(config_path)

    config = json.loads(config_path.read_text(encoding="utf-8"))
    expected = {
        "theme": "dark",
        "mcpServers": {
            "callback": {
                "command": "callback",
                "args": ["serve"],
            },
        },
    }
    assert config == expected


def test_configure_claude_is_idempotent(tmp_path):
    config_path = tmp_path / ".claude.json"

    configure_claude(config_path)
    first = json.loads(config_path.read_text(encoding="utf-8"))
    configure_claude(config_path)
    second = json.loads(config_path.read_text(encoding="utf-8"))

    assert first == second
    assert list(second["mcpServers"]) == ["callback"]


def test_configure_claude_preserves_existing_env(tmp_path):
    config_path = tmp_path / ".claude.json"
    config_path.write_text(
        json.dumps(
            {
                "mcpServers": {
                    "callback": {
                        "command": "old",
                        "args": ["serve"],
                        "env": {"CALLBACK_TRACE_BACKEND": "langsmith"},
                    }
                }
            }
        ),
        encoding="utf-8",
    )

    configure_claude(config_path, "/usr/local/bin/callback")

    config = json.loads(config_path.read_text(encoding="utf-8"))
    assert config["mcpServers"]["callback"] == {
        "command": "/usr/local/bin/callback",
        "args": ["serve"],
        "env": {"CALLBACK_TRACE_BACKEND": "langsmith"},
    }


def test_configure_codex_creates_entry_and_preserves_unrelated_keys(tmp_path):
    config_path = tmp_path / "config.toml"
    config_path.write_text('model = "gpt-5.5"\n[profiles.default]\nservice_tier = "fast"\n')

    configure_codex(config_path)

    config = _read_toml(config_path)
    expected = {
        "model": "gpt-5.5",
        "profiles": {"default": {"service_tier": "fast"}},
        "mcp_servers": {
            "callback": {
                "command": "callback",
                "args": ["serve"],
            },
        },
    }
    assert config == expected


def test_configure_codex_is_idempotent(tmp_path):
    config_path = tmp_path / "config.toml"

    configure_codex(config_path)
    first = _read_toml(config_path)
    configure_codex(config_path)
    second = _read_toml(config_path)

    assert first == second
    assert list(second["mcp_servers"]) == ["callback"]


def test_configure_codex_preserves_existing_env(tmp_path):
    config_path = tmp_path / "config.toml"
    config_path.write_text(
        (
            "[mcp_servers.callback]\n"
            'args = ["serve"]\n'
            'command = "old"\n'
            "[mcp_servers.callback.env]\n"
            'CALLBACK_TRACE_BACKEND = "langsmith"\n'
        ),
        encoding="utf-8",
    )

    configure_codex(config_path, "/usr/local/bin/callback")

    config = _read_toml(config_path)
    assert config["mcp_servers"]["callback"] == {
        "command": "/usr/local/bin/callback",
        "args": ["serve"],
        "env": {"CALLBACK_TRACE_BACKEND": "langsmith"},
    }


def test_setup_mcp_writes_both_configs(tmp_path):
    claude_path = tmp_path / ".claude.json"
    codex_path = tmp_path / ".codex" / "config.toml"
    mock_result = MagicMock()
    mock_result.returncode = 0

    with (
        patch("callback.cli._resolve_command", return_value="/usr/local/bin/callback"),
        patch("callback.cli.subprocess.run", return_value=mock_result) as mock_run,
    ):
        result = runner.invoke(
            app,
            [
                "setup-mcp",
                "--claude-config",
                str(claude_path),
                "--codex-config",
                str(codex_path),
            ],
        )

    assert result.exit_code == 0
    assert json.loads(claude_path.read_text(encoding="utf-8"))["mcpServers"]["callback"] == {
        "command": "/usr/local/bin/callback",
        "args": ["serve"],
    }
    assert _read_toml(codex_path)["mcp_servers"]["callback"] == {
        "command": "/usr/local/bin/callback",
        "args": ["serve"],
    }
    import sys

    mock_run.assert_called_once_with([sys.executable, "-m", "playwright", "install", "chromium"])
    assert "callback config langsmith" in result.stdout
    assert "restart your MCP host" in result.stdout


def test_setup_mcp_preserves_existing_env(tmp_path):
    claude_path = tmp_path / ".claude.json"
    codex_path = tmp_path / "config.toml"
    claude_path.write_text(
        json.dumps(
            {
                "mcpServers": {
                    "callback": {
                        "command": "old",
                        "args": ["serve"],
                        "env": {"LANGSMITH_PROJECT": "demo"},
                    }
                }
            }
        ),
        encoding="utf-8",
    )
    codex_path.write_text(
        (
            "[mcp_servers.callback]\n"
            'args = ["serve"]\n'
            'command = "old"\n'
            "[mcp_servers.callback.env]\n"
            'LANGSMITH_PROJECT = "demo"\n'
        ),
        encoding="utf-8",
    )

    with (
        patch("callback.cli._resolve_command", return_value="/usr/local/bin/callback"),
        patch("callback.cli.subprocess.run") as mock_run,
    ):
        result = runner.invoke(
            app,
            [
                "setup-mcp",
                "--skip-browsers",
                "--claude-config",
                str(claude_path),
                "--codex-config",
                str(codex_path),
            ],
        )

    assert result.exit_code == 0
    mock_run.assert_not_called()
    assert json.loads(claude_path.read_text(encoding="utf-8"))["mcpServers"]["callback"] == {
        "command": "/usr/local/bin/callback",
        "args": ["serve"],
        "env": {"LANGSMITH_PROJECT": "demo"},
    }
    assert _read_toml(codex_path)["mcp_servers"]["callback"] == {
        "command": "/usr/local/bin/callback",
        "args": ["serve"],
        "env": {"LANGSMITH_PROJECT": "demo"},
    }


def test_config_env_set_list_unset_claude(tmp_path):
    claude_path = tmp_path / ".claude.json"
    codex_path = tmp_path / "config.toml"

    result = runner.invoke(
        app,
        [
            "config",
            "env",
            "set",
            "LANGSMITH_API_KEY",
            "secret-value",
            "--target",
            "claude",
            "--claude-config",
            str(claude_path),
            "--codex-config",
            str(codex_path),
        ],
    )

    config = json.loads(claude_path.read_text(encoding="utf-8"))
    actual = {
        "exit_code": result.exit_code,
        "env": config["mcpServers"]["callback"]["env"],
        "codex_exists": codex_path.exists(),
    }
    expected = {
        "exit_code": 0,
        "env": {"LANGSMITH_API_KEY": "secret-value"},
        "codex_exists": False,
    }

    assert actual == expected

    list_result = runner.invoke(
        app,
        [
            "config",
            "env",
            "list",
            "--target",
            "claude",
            "--claude-config",
            str(claude_path),
        ],
    )

    actual = {
        "exit_code": list_result.exit_code,
        "redacted": "LANGSMITH_API_KEY=********" in list_result.stdout,
        "secret_hidden": "secret-value" not in list_result.stdout,
    }
    expected = {
        "exit_code": 0,
        "redacted": True,
        "secret_hidden": True,
    }

    assert actual == expected

    show_result = runner.invoke(
        app,
        [
            "config",
            "env",
            "list",
            "--target",
            "claude",
            "--claude-config",
            str(claude_path),
            "--show-secrets",
        ],
    )

    actual = {
        "exit_code": show_result.exit_code,
        "secret_shown": "LANGSMITH_API_KEY=secret-value" in show_result.stdout,
    }
    expected = {
        "exit_code": 0,
        "secret_shown": True,
    }

    assert actual == expected

    unset_result = runner.invoke(
        app,
        [
            "config",
            "env",
            "unset",
            "LANGSMITH_API_KEY",
            "--target",
            "claude",
            "--claude-config",
            str(claude_path),
        ],
    )

    config = json.loads(claude_path.read_text(encoding="utf-8"))
    actual = {
        "exit_code": unset_result.exit_code,
        "env": config["mcpServers"]["callback"]["env"],
    }
    expected = {
        "exit_code": 0,
        "env": {},
    }

    assert actual == expected


def test_config_env_set_unset_codex(tmp_path):
    codex_path = tmp_path / "config.toml"

    set_result = runner.invoke(
        app,
        [
            "config",
            "env",
            "set",
            "CALLBACK_TRACE_BACKEND",
            "langsmith",
            "--target",
            "codex",
            "--codex-config",
            str(codex_path),
        ],
    )

    config = _read_toml(codex_path)
    actual = {
        "exit_code": set_result.exit_code,
        "env": config["mcp_servers"]["callback"]["env"],
    }
    expected = {
        "exit_code": 0,
        "env": {"CALLBACK_TRACE_BACKEND": "langsmith"},
    }

    assert actual == expected

    unset_result = runner.invoke(
        app,
        [
            "config",
            "env",
            "unset",
            "CALLBACK_TRACE_BACKEND",
            "--target",
            "codex",
            "--codex-config",
            str(codex_path),
        ],
    )

    config = _read_toml(codex_path)
    actual = {
        "exit_code": unset_result.exit_code,
        "env": config["mcp_servers"]["callback"]["env"],
    }
    expected = {
        "exit_code": 0,
        "env": {},
    }

    assert actual == expected


def test_config_env_list_prints_literal_target_headers(tmp_path):
    claude_path = tmp_path / ".claude.json"
    claude_path.write_text(
        json.dumps(
            {
                "mcpServers": {
                    "callback": {
                        "command": "callback",
                        "args": ["serve"],
                        "env": {"LANGSMITH_PROJECT": "Callback"},
                    }
                }
            }
        ),
        encoding="utf-8",
    )

    result = runner.invoke(
        app,
        [
            "config",
            "env",
            "list",
            "--target",
            "claude",
            "--claude-config",
            str(claude_path),
        ],
    )

    actual = {
        "exit_code": result.exit_code,
        "has_header": "[claude]" in result.stdout,
        "has_env": "LANGSMITH_PROJECT=Callback" in result.stdout,
    }
    expected = {
        "exit_code": 0,
        "has_header": True,
        "has_env": True,
    }

    assert actual == expected


def test_config_status_reports_same_env_for_all_targets(tmp_path):
    claude_path = tmp_path / ".claude.json"
    codex_path = tmp_path / "config.toml"
    expected_env = {
        "CALLBACK_TRACE_BACKEND": "langsmith",
        "LANGSMITH_TRACING": "true",
        "LANGSMITH_API_KEY": "lsv2-secret",
    }
    claude_path.write_text(
        json.dumps(
            {
                "mcpServers": {
                    "callback": {
                        "command": "callback",
                        "args": ["serve"],
                        "env": expected_env,
                    }
                }
            }
        ),
        encoding="utf-8",
    )
    codex_path.write_text(
        (
            "[mcp_servers.callback]\n"
            'command = "callback"\n'
            'args = ["serve"]\n'
            "[mcp_servers.callback.env]\n"
            'CALLBACK_TRACE_BACKEND = "langsmith"\n'
            'LANGSMITH_TRACING = "true"\n'
            'LANGSMITH_API_KEY = "lsv2-secret"\n'
        ),
        encoding="utf-8",
    )

    result = runner.invoke(
        app,
        [
            "config",
            "status",
            "--claude-config",
            str(claude_path),
            "--codex-config",
            str(codex_path),
        ],
    )

    actual = {
        "exit_code": result.exit_code,
        "has_backend": "CALLBACK_TRACE_BACKEND" in result.stdout,
        "has_same": "same" in result.stdout,
        "redacts_key": "LANGSMITH_API_KEY" in result.stdout
        and "********" in result.stdout
        and "lsv2-secret" not in result.stdout,
    }
    expected = {
        "exit_code": 0,
        "has_backend": True,
        "has_same": True,
        "redacts_key": True,
    }

    assert actual == expected


def test_config_status_reports_missing_and_different_values(tmp_path):
    claude_path = tmp_path / ".claude.json"
    codex_path = tmp_path / "config.toml"
    claude_path.write_text(
        json.dumps(
            {
                "mcpServers": {
                    "callback": {
                        "command": "callback",
                        "args": ["serve"],
                        "env": {
                            "LANGSMITH_PROJECT": "Callback",
                            "LANGSMITH_TRACING": "true",
                        },
                    }
                }
            }
        ),
        encoding="utf-8",
    )
    codex_path.write_text(
        (
            "[mcp_servers.callback]\n"
            'command = "callback"\n'
            'args = ["serve"]\n'
            "[mcp_servers.callback.env]\n"
            'LANGSMITH_PROJECT = "Other"\n'
        ),
        encoding="utf-8",
    )

    result = runner.invoke(
        app,
        [
            "config",
            "status",
            "--claude-config",
            str(claude_path),
            "--codex-config",
            str(codex_path),
        ],
    )

    actual = {
        "exit_code": result.exit_code,
        "project_different": "LANGSMITH_PROJECT" in result.stdout and "different" in result.stdout,
        "tracing_missing": "LANGSMITH_TRACING" in result.stdout and "missing" in result.stdout,
        "shows_unset_cell": "(unset)" in result.stdout,
    }
    expected = {
        "exit_code": 0,
        "project_different": True,
        "tracing_missing": True,
        "shows_unset_cell": True,
    }

    assert actual == expected


def test_config_status_show_secrets_reveals_secret_values(tmp_path):
    claude_path = tmp_path / ".claude.json"
    codex_path = tmp_path / "config.toml"
    claude_path.write_text(
        json.dumps(
            {
                "mcpServers": {
                    "callback": {
                        "command": "callback",
                        "args": ["serve"],
                        "env": {"LANGSMITH_API_KEY": "lsv2-secret"},
                    }
                }
            }
        ),
        encoding="utf-8",
    )
    codex_path.write_text(
        (
            "[mcp_servers.callback]\n"
            'command = "callback"\n'
            'args = ["serve"]\n'
            "[mcp_servers.callback.env]\n"
            'LANGSMITH_API_KEY = "lsv2-secret"\n'
        ),
        encoding="utf-8",
    )

    result = runner.invoke(
        app,
        [
            "config",
            "status",
            "--show-secrets",
            "--claude-config",
            str(claude_path),
            "--codex-config",
            str(codex_path),
        ],
    )

    actual = {
        "exit_code": result.exit_code,
        "shows_secret": "lsv2-secret" in result.stdout,
        "does_not_redact": "********" not in result.stdout,
    }
    expected = {
        "exit_code": 0,
        "shows_secret": True,
        "does_not_redact": True,
    }

    assert actual == expected


def test_config_status_target_claude_does_not_read_or_write_codex(tmp_path):
    claude_path = tmp_path / ".claude.json"
    codex_path = tmp_path / "config.toml"
    claude_path.write_text(
        json.dumps(
            {
                "mcpServers": {
                    "callback": {
                        "command": "callback",
                        "args": ["serve"],
                        "env": {"LANGSMITH_PROJECT": "Callback"},
                    }
                }
            }
        ),
        encoding="utf-8",
    )

    result = runner.invoke(
        app,
        [
            "config",
            "status",
            "--target",
            "claude",
            "--claude-config",
            str(claude_path),
            "--codex-config",
            str(codex_path),
        ],
    )

    actual = {
        "exit_code": result.exit_code,
        "has_claude_value": "Callback" in result.stdout,
        "codex_not_checked": "not checked" in result.stdout,
        "codex_exists": codex_path.exists(),
    }
    expected = {
        "exit_code": 0,
        "has_claude_value": True,
        "codex_not_checked": True,
        "codex_exists": False,
    }

    assert actual == expected


def test_config_status_missing_env_maps_reports_unset_without_writing(tmp_path):
    claude_path = tmp_path / ".claude.json"
    codex_path = tmp_path / "config.toml"

    result = runner.invoke(
        app,
        [
            "config",
            "status",
            "--claude-config",
            str(claude_path),
            "--codex-config",
            str(codex_path),
        ],
    )

    actual = {
        "exit_code": result.exit_code,
        "has_none": "(none)" in result.stdout,
        "has_unset": "unset" in result.stdout,
        "claude_exists": claude_path.exists(),
        "codex_exists": codex_path.exists(),
    }
    expected = {
        "exit_code": 0,
        "has_none": True,
        "has_unset": True,
        "claude_exists": False,
        "codex_exists": False,
    }

    assert actual == expected


def test_config_env_rejects_invalid_name_without_writing(tmp_path):
    claude_path = tmp_path / ".claude.json"

    result = runner.invoke(
        app,
        [
            "config",
            "env",
            "set",
            "bad-name",
            "value",
            "--target",
            "claude",
            "--claude-config",
            str(claude_path),
        ],
    )

    assert result.exit_code == 1
    assert "invalid env var name" in result.stderr
    assert not claude_path.exists()


def test_config_langsmith_sets_expected_env_for_all_targets(tmp_path):
    claude_path = tmp_path / ".claude.json"
    codex_path = tmp_path / "config.toml"

    result = runner.invoke(
        app,
        [
            "config",
            "langsmith",
            "--api-key",
            "lsv2-key",
            "--project",
            "callback-demo",
            "--target",
            "all",
            "--claude-config",
            str(claude_path),
            "--codex-config",
            str(codex_path),
        ],
    )

    expected_env = {
        "CALLBACK_TRACE_BACKEND": "langsmith",
        "LANGSMITH_TRACING": "true",
        "LANGSMITH_API_KEY": "lsv2-key",
        "LANGSMITH_ENDPOINT": "https://api.smith.langchain.com",
        "LANGSMITH_PROJECT": "callback-demo",
    }
    assert result.exit_code == 0
    assert (
        json.loads(claude_path.read_text(encoding="utf-8"))["mcpServers"]["callback"]["env"]
        == expected_env
    )
    assert _read_toml(codex_path)["mcp_servers"]["callback"]["env"] == expected_env


def test_config_langsmith_defaults_to_callback_project_and_langsmith_endpoint(tmp_path):
    claude_path = tmp_path / ".claude.json"
    codex_path = tmp_path / "config.toml"

    result = runner.invoke(
        app,
        [
            "config",
            "langsmith",
            "--api-key",
            "lsv2-key",
            "--target",
            "claude",
            "--claude-config",
            str(claude_path),
            "--codex-config",
            str(codex_path),
        ],
    )

    actual = {
        "exit_code": result.exit_code,
        "env": json.loads(claude_path.read_text(encoding="utf-8"))["mcpServers"]["callback"]["env"],
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


def test_trace_check_reports_missing_langsmith_key(monkeypatch):
    monkeypatch.setenv("CALLBACK_TRACE_BACKEND", "langsmith")
    monkeypatch.setenv("LANGSMITH_TRACING", "true")
    monkeypatch.delenv("LANGSMITH_API_KEY", raising=False)

    result = runner.invoke(app, ["trace-check"])

    assert result.exit_code == 1
    assert "LANGSMITH_API_KEY is required" in result.stderr


def test_trace_check_claude_reads_config_and_emits_safe_trace(tmp_path):
    claude_path = tmp_path / ".claude.json"
    claude_path.write_text(
        json.dumps(
            {
                "mcpServers": {
                    "callback": {
                        "command": "callback",
                        "args": ["serve"],
                        "env": {
                            "CALLBACK_TRACE_BACKEND": "langsmith",
                            "LANGSMITH_TRACING": "true",
                            "LANGSMITH_API_KEY": "lsv2-secret",
                            "LANGSMITH_PROJECT": "callback-demo",
                        },
                    }
                }
            }
        ),
        encoding="utf-8",
    )

    class FakeClient:
        def list_projects(self, limit: int):
            assert limit == 1
            return iter([object()])

    with (
        patch("callback.cli._make_langsmith_client", return_value=FakeClient()) as make_client,
        patch("callback.cli.emit_trace_check_probe") as emit_trace,
    ):
        result = runner.invoke(
            app,
            [
                "trace-check",
                "--target",
                "claude",
                "--claude-config",
                str(claude_path),
                "--emit-test-trace",
            ],
        )

    assert result.exit_code == 0
    assert "claude: ok" in result.stdout
    assert "lsv2-secret" not in result.stdout
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


def test_setup_mcp_skip_browsers_writes_configs_without_install(tmp_path):
    claude_path = tmp_path / ".claude.json"
    codex_path = tmp_path / ".codex" / "config.toml"

    with (
        patch("callback.cli._resolve_command", return_value="/usr/local/bin/callback"),
        patch("callback.cli.subprocess.run") as mock_run,
    ):
        result = runner.invoke(
            app,
            [
                "setup-mcp",
                "--skip-browsers",
                "--claude-config",
                str(claude_path),
                "--codex-config",
                str(codex_path),
            ],
        )

    assert result.exit_code == 0
    mock_run.assert_not_called()
    assert json.loads(claude_path.read_text(encoding="utf-8"))["mcpServers"]["callback"] == {
        "command": "/usr/local/bin/callback",
        "args": ["serve"],
    }
    assert _read_toml(codex_path)["mcp_servers"]["callback"] == {
        "command": "/usr/local/bin/callback",
        "args": ["serve"],
    }


def test_setup_mcp_browser_install_failure_leaves_configs_unwritten(tmp_path):
    claude_path = tmp_path / ".claude.json"
    codex_path = tmp_path / ".codex" / "config.toml"
    mock_result = MagicMock()
    mock_result.returncode = 7

    with patch("callback.cli.subprocess.run", return_value=mock_result):
        result = runner.invoke(
            app,
            [
                "setup-mcp",
                "--claude-config",
                str(claude_path),
                "--codex-config",
                str(codex_path),
            ],
        )

    assert result.exit_code == 7
    assert "browser install failed" in result.stderr
    assert not claude_path.exists()
    assert not codex_path.exists()


def test_setup_mcp_rejects_invalid_codex_toml_without_overwrite(tmp_path):
    claude_path = tmp_path / ".claude.json"
    codex_path = tmp_path / "config.toml"
    original = "[broken"
    codex_path.write_text(original, encoding="utf-8")

    with patch("callback.cli.subprocess.run") as mock_run:
        result = runner.invoke(
            app,
            [
                "setup-mcp",
                "--claude-config",
                str(claude_path),
                "--codex-config",
                str(codex_path),
            ],
        )

    assert result.exit_code == 1
    assert "not valid TOML" in result.stderr
    assert codex_path.read_text(encoding="utf-8") == original
    mock_run.assert_not_called()


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
        patch("callback.cli._DATA_DIR", data_dir),
        patch("callback.cli._STATE_DIR", state_dir),
        patch("callback.cli._remove_server_from_claude"),
        patch("callback.cli._remove_server_from_codex"),
    ):
        result = runner.invoke(app, ["uninstall"])

    assert result.exit_code == 0
    assert data_dir.exists()


def test_uninstall_purge_deletes_data_and_state_dirs(tmp_path):
    data_dir = tmp_path / "share"
    state_dir = tmp_path / "state"
    data_dir.mkdir()
    state_dir.mkdir()

    with (
        patch("callback.cli._DATA_DIR", data_dir),
        patch("callback.cli._STATE_DIR", state_dir),
        patch("callback.cli._remove_server_from_claude"),
        patch("callback.cli._remove_server_from_codex"),
    ):
        result = runner.invoke(app, ["uninstall", "--purge"])

    assert result.exit_code == 0
    assert not data_dir.exists()
    assert not state_dir.exists()


def test_uninstall_purge_skips_absent_dirs(tmp_path):
    data_dir = tmp_path / "share"
    state_dir = tmp_path / "state"

    with (
        patch("callback.cli._DATA_DIR", data_dir),
        patch("callback.cli._STATE_DIR", state_dir),
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
