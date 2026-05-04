"""Tests for the pi-apply CLI."""

from __future__ import annotations

import json
import tomllib
from pathlib import Path
from unittest.mock import Mock, patch

from typer.testing import CliRunner

from pi_apply.cli import app, configure_claude, configure_codex

runner = CliRunner()


def _read_toml(path: Path) -> dict:
    with path.open("rb") as handle:
        return tomllib.load(handle)


def test_cli_help_lists_commands():
    result = runner.invoke(app, ["--help"])

    assert result.exit_code == 0
    for command in ("serve", "setup-mcp", "logs", "version"):
        assert command in result.stdout


def test_version_prints_installed_distribution_version(monkeypatch):
    monkeypatch.setattr("pi_apply.cli.importlib.metadata.version", lambda name: "0.1.0")

    result = runner.invoke(app, ["version"])

    assert result.exit_code == 0
    assert result.stdout.strip() == "0.1.0"


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
        "command": "pi-apply",
        "args": ["serve"],
    }
    assert _read_toml(codex_path)["mcp_servers"]["pi-apply"] == {
        "command": "pi-apply",
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
