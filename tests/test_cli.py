"""Tests for the pi-apply CLI."""

from __future__ import annotations

import json
import tomllib
from pathlib import Path
from unittest.mock import MagicMock, Mock, patch

from typer.testing import CliRunner

from pi_apply.cli import app, configure_claude, configure_codex

runner = CliRunner()


def _read_toml(path: Path) -> dict:
    with path.open("rb") as handle:
        return tomllib.load(handle)


def test_cli_help_lists_commands():
    result = runner.invoke(app, ["--help"])

    assert result.exit_code == 0
    commands = ("serve", "setup-mcp", "install-browsers", "uninstall", "update", "logs", "version")
    for command in commands:
        assert command in result.stdout


def test_version_prints_installed_distribution_version(monkeypatch):
    monkeypatch.setattr("pi_apply.cli._read_build_version", lambda: None)
    monkeypatch.setattr("pi_apply.cli.importlib.metadata.version", lambda name: "0.1.0")

    result = runner.invoke(app, ["version"])

    assert result.exit_code == 0
    assert result.stdout.strip() == "0.1.0"


def test_version_prefers_generated_build_version(monkeypatch):
    monkeypatch.setattr("pi_apply.cli._read_build_version", lambda: "0.3.0-01-abc1234")
    monkeypatch.setattr("pi_apply.cli.importlib.metadata.version", lambda name: "0.3.0")

    result = runner.invoke(app, ["version"])

    assert result.exit_code == 0
    assert result.stdout.strip() == "0.3.0-01-abc1234"


def test_serve_uses_server_runner():
    run = Mock()

    with patch("pi_apply.server.run", run):
        result = runner.invoke(app, ["serve"])

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


def test_configure_claude_creates_entry_and_preserves_unrelated_keys(tmp_path):
    config_path = tmp_path / ".claude.json"
    config_path.write_text(json.dumps({"theme": "dark"}), encoding="utf-8")

    configure_claude(config_path)

    config = json.loads(config_path.read_text(encoding="utf-8"))
    expected = {
        "theme": "dark",
        "mcpServers": {
            "pi-apply": {
                "command": "pi-apply",
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
    assert list(second["mcpServers"]) == ["pi-apply"]


def test_configure_codex_creates_entry_and_preserves_unrelated_keys(tmp_path):
    config_path = tmp_path / "config.toml"
    config_path.write_text('model = "gpt-5.5"\n[profiles.default]\nservice_tier = "fast"\n')

    configure_codex(config_path)

    config = _read_toml(config_path)
    expected = {
        "model": "gpt-5.5",
        "profiles": {"default": {"service_tier": "fast"}},
        "mcp_servers": {
            "pi-apply": {
                "command": "pi-apply",
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
    assert list(second["mcp_servers"]) == ["pi-apply"]


def test_setup_mcp_writes_both_configs(tmp_path):
    claude_path = tmp_path / ".claude.json"
    codex_path = tmp_path / ".codex" / "config.toml"

    with patch("pi_apply.cli._resolve_command", return_value="/usr/local/bin/pi-apply"):
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
    assert json.loads(claude_path.read_text(encoding="utf-8"))["mcpServers"]["pi-apply"] == {
        "command": "/usr/local/bin/pi-apply",
        "args": ["serve"],
    }
    assert _read_toml(codex_path)["mcp_servers"]["pi-apply"] == {
        "command": "/usr/local/bin/pi-apply",
        "args": ["serve"],
    }


def test_setup_mcp_rejects_invalid_codex_toml_without_overwrite(tmp_path):
    claude_path = tmp_path / ".claude.json"
    codex_path = tmp_path / "config.toml"
    original = "[broken"
    codex_path.write_text(original, encoding="utf-8")

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


# ============================================================================
# install-browsers, uninstall, update
# ============================================================================


def test_install_browsers_calls_playwright():
    mock_result = MagicMock()
    mock_result.returncode = 0

    with patch("pi_apply.cli.subprocess.run", return_value=mock_result) as mock_run:
        result = runner.invoke(app, ["install-browsers"])

    import sys

    mock_run.assert_called_once_with([sys.executable, "-m", "playwright", "install", "chromium"])
    assert result.exit_code == 0


def test_uninstall_removes_claude_entry(tmp_path):
    from pi_apply.cli import _remove_server_from_claude

    claude_path = tmp_path / ".claude.json"
    entry = {"command": "pi-apply", "args": ["serve"]}
    existing = {"theme": "dark", "mcpServers": {"pi-apply": entry}}
    claude_path.write_text(json.dumps(existing), encoding="utf-8")

    _remove_server_from_claude(claude_path)

    config = json.loads(claude_path.read_text(encoding="utf-8"))
    assert config == {"theme": "dark", "mcpServers": {}}


def test_uninstall_skips_missing_config_files(tmp_path):
    from pi_apply.cli import _remove_server_from_claude, _remove_server_from_codex

    missing_claude = tmp_path / ".claude.json"
    missing_codex = tmp_path / "config.toml"

    _remove_server_from_claude(missing_claude)
    _remove_server_from_codex(missing_codex)

    assert not missing_claude.exists()
    assert not missing_codex.exists()


def test_uninstall_without_purge_preserves_data_dir(tmp_path):
    data_dir = tmp_path / "pi-apply-data"
    data_dir.mkdir()

    state_dir = tmp_path / "state"
    with patch("pi_apply.cli._DATA_DIR", data_dir), patch("pi_apply.cli._STATE_DIR", state_dir):
        runner.invoke(app, ["uninstall"])

    assert data_dir.exists()


def test_uninstall_purge_deletes_data_and_state_dirs(tmp_path):
    data_dir = tmp_path / "share"
    state_dir = tmp_path / "state"
    data_dir.mkdir()
    state_dir.mkdir()

    with patch("pi_apply.cli._DATA_DIR", data_dir), patch("pi_apply.cli._STATE_DIR", state_dir):
        runner.invoke(app, ["uninstall", "--purge"])

    assert not data_dir.exists()
    assert not state_dir.exists()


def test_uninstall_purge_skips_absent_dirs(tmp_path):
    data_dir = tmp_path / "share"
    state_dir = tmp_path / "state"

    with patch("pi_apply.cli._DATA_DIR", data_dir), patch("pi_apply.cli._STATE_DIR", state_dir):
        invoke_result = runner.invoke(app, ["uninstall", "--purge"])

    assert invoke_result.exit_code == 0


def test_update_calls_uv_tool_upgrade():
    mock_result = MagicMock()
    mock_result.returncode = 0

    with patch("pi_apply.cli.subprocess.run", return_value=mock_result) as mock_run:
        result = runner.invoke(app, ["update"])

    mock_run.assert_called_once_with(["uv", "tool", "upgrade", "pi-apply"])
    assert result.exit_code == 0
