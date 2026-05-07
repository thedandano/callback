"""Command-line interface for pi-apply."""

from __future__ import annotations

import importlib.metadata
import json
import re
import shutil
import subprocess
import sys
import tempfile
import time
import tomllib
from collections.abc import Mapping, Sequence
from pathlib import Path
from typing import Annotated, Any

import typer
from rich.console import Console

app = typer.Typer(no_args_is_help=True)
console = Console(soft_wrap=True)
error_console = Console(stderr=True, soft_wrap=True)

SERVER_NAME = "pi-apply"
SERVER_COMMAND = "pi-apply"
SERVER_ARGS = ["serve"]
DEFAULT_LOG_PATH = Path("~/.local/state/pi-apply/server.log").expanduser()
_DATA_DIR = Path("~/.local/share/pi-apply").expanduser()
_STATE_DIR = Path("~/.local/state/pi-apply").expanduser()


class ConfigError(Exception):
    """Raised when an MCP config file cannot be safely updated."""


def _resolve_command() -> str:
    """Return absolute path to the pi-apply binary, falling back to the bare name."""
    return shutil.which(SERVER_COMMAND) or SERVER_COMMAND


def mcp_server_config(command: str | None = None) -> dict[str, object]:
    """Return the launcher config shared by supported MCP clients."""
    return {"command": command or SERVER_COMMAND, "args": list(SERVER_ARGS)}


def _write_text_atomic(path: Path, content: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.NamedTemporaryFile("w", encoding="utf-8", dir=path.parent, delete=False) as tmp:
        tmp.write(content)
        tmp_path = Path(tmp.name)
    tmp_path.replace(path)


def _read_json_config(path: Path) -> dict[str, Any]:
    if not path.exists():
        return {}
    try:
        loaded = json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        raise ConfigError(f"{path} is not valid JSON: {exc.msg}") from exc
    if not isinstance(loaded, dict):
        raise ConfigError(f"{path} must contain a JSON object")
    return loaded


def configure_claude(path: Path, command: str | None = None) -> None:
    """Write the Claude MCP server entry, preserving unrelated config keys."""
    config = _read_json_config(path)
    servers = config.setdefault("mcpServers", {})
    if not isinstance(servers, dict):
        raise ConfigError(f'{path} key "mcpServers" must be an object')
    servers[SERVER_NAME] = mcp_server_config(command)
    _write_text_atomic(path, json.dumps(config, indent=2, sort_keys=True) + "\n")


def _read_toml_config(path: Path) -> dict[str, Any]:
    if not path.exists():
        return {}
    try:
        with path.open("rb") as handle:
            loaded = tomllib.load(handle)
    except tomllib.TOMLDecodeError as exc:
        raise ConfigError(f"{path} is not valid TOML: {exc}") from exc
    return dict(loaded)


_BARE_TOML_KEY = re.compile(r"^[A-Za-z0-9_-]+$")


def _toml_key(key: str) -> str:
    if _BARE_TOML_KEY.match(key):
        return key
    return json.dumps(key)


def _toml_value(value: object) -> str:
    if isinstance(value, str):
        return json.dumps(value)
    if isinstance(value, bool):
        return "true" if value else "false"
    if isinstance(value, int | float):
        return str(value)
    if isinstance(value, Sequence) and not isinstance(value, str | bytes | bytearray):
        return "[" + ", ".join(_toml_value(item) for item in value) + "]"
    raise ConfigError(f"cannot serialize TOML value of type {type(value).__name__}")


def _toml_lines(config: Mapping[str, Any], prefix: tuple[str, ...] = ()) -> list[str]:
    scalar_lines: list[str] = []
    table_lines: list[str] = []

    for key in sorted(config):
        value = config[key]
        if isinstance(value, Mapping):
            table_name = ".".join(_toml_key(part) for part in (*prefix, key))
            table_lines.append(f"[{table_name}]")
            table_lines.extend(_toml_lines(value, (*prefix, key)))
            table_lines.append("")
        else:
            scalar_lines.append(f"{_toml_key(key)} = {_toml_value(value)}")

    if scalar_lines and table_lines:
        return [*scalar_lines, "", *table_lines]
    return [*scalar_lines, *table_lines]


def _dump_toml(config: Mapping[str, Any]) -> str:
    lines = _toml_lines(config)
    while lines and lines[-1] == "":
        lines.pop()
    return "\n".join(lines) + "\n"


def configure_codex(path: Path, command: str | None = None) -> None:
    """Write the Codex MCP server entry, preserving parseable config keys."""
    config = _read_toml_config(path)
    servers = config.setdefault("mcp_servers", {})
    if not isinstance(servers, dict):
        raise ConfigError(f'{path} key "mcp_servers" must be a table')
    servers[SERVER_NAME] = mcp_server_config(command)
    _write_text_atomic(path, _dump_toml(config))


def _remove_server_from_claude(path: Path) -> None:
    if not path.exists():
        return
    config = _read_json_config(path)
    servers = config.get("mcpServers")
    if isinstance(servers, dict):
        servers.pop(SERVER_NAME, None)
    _write_text_atomic(path, json.dumps(config, indent=2, sort_keys=True) + "\n")


def _remove_server_from_codex(path: Path) -> None:
    if not path.exists():
        return
    config = _read_toml_config(path)
    servers = config.get("mcp_servers")
    if isinstance(servers, dict):
        servers.pop(SERVER_NAME, None)
    _write_text_atomic(path, _dump_toml(config))


@app.command()
def serve() -> None:
    """Start the pi-apply MCP server."""
    from pi_apply.server import run

    run()


@app.command("setup-mcp")
def setup_mcp(
    claude_config: Annotated[
        Path | None,
        typer.Option("--claude-config", help="Claude JSON config path."),
    ] = None,
    codex_config: Annotated[
        Path | None,
        typer.Option("--codex-config", help="Codex TOML config path."),
    ] = None,
) -> None:
    """Install pi-apply MCP server entries for Claude and Codex."""
    claude_path = claude_config or Path("~/.claude.json").expanduser()
    codex_path = codex_config or Path("~/.codex/config.toml").expanduser()
    command = _resolve_command()
    try:
        configure_claude(claude_path, command)
        configure_codex(codex_path, command)
    except ConfigError as exc:
        error_console.print(f"setup-mcp failed: {exc}")
        raise typer.Exit(1) from exc

    console.print(f"Updated Claude config: {claude_path}")
    console.print(f"Updated Codex config: {codex_path}")


@app.command()
def logs(
    log_path: Annotated[Path, typer.Option("--log-path", help="Server log path.")] = (
        DEFAULT_LOG_PATH
    ),
    lines: Annotated[
        int, typer.Option("--lines", "-n", min=1, help="Number of trailing lines.")
    ] = 50,
    follow: Annotated[
        bool,
        typer.Option("--follow", help="Continue streaming new log lines."),
    ] = False,
) -> None:
    """Print the tail of the pi-apply server log."""
    if not log_path.exists():
        error_console.print(f"Log file not found: {log_path}")
        raise typer.Exit(1)

    with log_path.open(encoding="utf-8") as handle:
        entries = handle.readlines()
        for line in entries[-lines:]:
            console.print(line.rstrip("\n"))

        if follow:
            while True:
                line = handle.readline()
                if line:
                    console.print(line.rstrip("\n"))
                else:
                    time.sleep(0.5)


@app.command("install-browsers")
def install_browsers() -> None:
    """Install Playwright Chromium browser in the tool's isolated environment."""
    result = subprocess.run(
        [sys.executable, "-m", "playwright", "install", "chromium"],
    )
    raise typer.Exit(result.returncode)


@app.command()
def uninstall(
    purge: Annotated[
        bool,
        typer.Option("--purge", help="Also delete application data and state directories."),
    ] = False,
) -> None:
    """Remove pi-apply MCP server entries from Claude and Codex configs."""
    claude_path = Path("~/.claude.json").expanduser()
    codex_path = Path("~/.codex/config.toml").expanduser()
    try:
        _remove_server_from_claude(claude_path)
        _remove_server_from_codex(codex_path)
    except ConfigError as exc:
        error_console.print(f"uninstall failed: {exc}")
        raise typer.Exit(1) from exc

    if purge:
        import shutil

        for directory in (_DATA_DIR, _STATE_DIR):
            if directory.exists():
                shutil.rmtree(directory)
                console.print(f"Deleted: {directory}")


@app.command()
def update() -> None:
    """Upgrade pi-apply to the latest version via uv."""
    result = subprocess.run(["uv", "tool", "upgrade", "pi-apply"])
    raise typer.Exit(result.returncode)


@app.command()
def version() -> None:
    """Print the installed pi-apply package version."""
    try:
        console.print(importlib.metadata.version("pi-apply"))
    except importlib.metadata.PackageNotFoundError as exc:
        error_console.print("pi-apply is not installed as a package")
        raise typer.Exit(1) from exc


if __name__ == "__main__":
    app()
