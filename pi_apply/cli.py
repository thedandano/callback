"""Command-line interface for pi-apply."""

from __future__ import annotations

import datetime
import importlib.metadata
import json
import os
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
CODEX_SERVER_ARGS = ["serve", "--project-logs"]
DEFAULT_LOG_PATH = Path("~/.local/state/pi-apply/server.log").expanduser()
_DATA_DIR = Path("~/.local/share/pi-apply").expanduser()
_STATE_DIR = Path("~/.local/state/pi-apply").expanduser()


class ConfigError(Exception):
    """Raised when an MCP config file cannot be safely updated."""


def _resolve_command() -> str:
    """Return absolute path to the pi-apply binary, falling back to the bare name."""
    return shutil.which(SERVER_COMMAND) or SERVER_COMMAND


def mcp_server_config(
    command: str | None = None,
    *,
    project_logs: bool = False,
) -> dict[str, object]:
    """Return the launcher config shared by supported MCP clients."""
    args = CODEX_SERVER_ARGS if project_logs else SERVER_ARGS
    return {"command": command or SERVER_COMMAND, "args": list(args)}


def _project_log_path() -> Path:
    return Path.cwd() / ".pi-apply" / "server.log"


def _resolve_log_path(
    log_path: Path | None = None,
    *,
    project_logs: bool = False,
    auto_project: bool = False,
) -> Path:
    """Resolve the audit log path for commands that read or write server logs."""
    if log_path is not None:
        return log_path.expanduser()

    project_log_path = _project_log_path()
    if project_logs or (auto_project and project_log_path.exists()):
        return project_log_path

    return DEFAULT_LOG_PATH


def _write_startup_log_event(log_path: Path, line: str) -> None:
    log_path.parent.mkdir(parents=True, exist_ok=True)
    with log_path.open("a", encoding="utf-8") as handle:
        handle.write(line + "\n")


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
    servers[SERVER_NAME] = mcp_server_config(command, project_logs=True)
    _write_text_atomic(path, _dump_toml(config))


def _validate_claude_config(path: Path) -> None:
    config = _read_json_config(path)
    servers = config.get("mcpServers", {})
    if not isinstance(servers, dict):
        raise ConfigError(f'{path} key "mcpServers" must be an object')


def _validate_codex_config(path: Path) -> None:
    config = _read_toml_config(path)
    servers = config.get("mcp_servers", {})
    if not isinstance(servers, dict):
        raise ConfigError(f'{path} key "mcp_servers" must be a table')


def _install_browsers() -> int:
    result = subprocess.run(
        [sys.executable, "-m", "playwright", "install", "chromium"],
    )
    return result.returncode


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
def serve(
    log_path: Annotated[
        Path | None,
        typer.Option("--log-path", help="Server log path."),
    ] = None,
    project_logs: Annotated[
        bool,
        typer.Option(
            "--project-logs",
            help="Write logs to .pi-apply/server.log under the current project.",
        ),
    ] = False,
) -> None:
    """Start the pi-apply MCP server."""
    resolved_log_path = _resolve_log_path(log_path, project_logs=project_logs)
    os.environ["PI_APPLY_LOG_PATH"] = str(resolved_log_path)
    startup_event = json.dumps(
        {
            "event": "cli_serve_start",
            "timestamp": datetime.datetime.now(datetime.UTC).isoformat(),
            "level": "INFO",
        }
    )
    try:
        _write_startup_log_event(resolved_log_path, startup_event)
    except OSError as exc:
        error_console.print(
            json.dumps(
                {
                    "event": "cli_serve_log_unavailable",
                    "timestamp": datetime.datetime.now(datetime.UTC).isoformat(),
                    "level": "WARNING",
                    "path": str(resolved_log_path),
                    "error": str(exc),
                }
            )
        )

    from pi_apply.server import configure_logging, run

    configure_logging(str(resolved_log_path))

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
    skip_browsers: Annotated[
        bool,
        typer.Option(
            "--skip-browsers",
            help="Skip Playwright Chromium installation during setup.",
        ),
    ] = False,
) -> None:
    """Install pi-apply MCP server entries for Claude and Codex."""
    claude_path = claude_config or Path("~/.claude.json").expanduser()
    codex_path = codex_config or Path("~/.codex/config.toml").expanduser()
    command = _resolve_command()
    try:
        _validate_claude_config(claude_path)
        _validate_codex_config(codex_path)
        if not skip_browsers:
            console.print("Installing Playwright Chromium for pi-apply...")
            browser_install_returncode = _install_browsers()
            if browser_install_returncode != 0:
                error_console.print(
                    "setup-mcp failed: browser install failed; "
                    "run `pi-apply install-browsers` for details"
                )
                raise typer.Exit(browser_install_returncode)
        configure_claude(claude_path, command)
        configure_codex(codex_path, command)
    except ConfigError as exc:
        error_console.print(f"setup-mcp failed: {exc}")
        raise typer.Exit(1) from exc

    console.print(f"Updated Claude config: {claude_path}")
    console.print(f"Updated Codex config: {codex_path}")


@app.command()
def logs(
    log_path: Annotated[
        Path | None,
        typer.Option("--log-path", help="Server log path."),
    ] = None,
    lines: Annotated[
        int, typer.Option("--lines", "-n", min=1, help="Number of trailing lines.")
    ] = 50,
    follow: Annotated[
        bool,
        typer.Option("--follow", help="Continue streaming new log lines."),
    ] = False,
    project_logs: Annotated[
        bool,
        typer.Option(
            "--project-logs",
            help="Read logs from .pi-apply/server.log under the current project.",
        ),
    ] = False,
) -> None:
    """Print the tail of the pi-apply server log."""
    resolved_log_path = _resolve_log_path(
        log_path,
        project_logs=project_logs,
        auto_project=True,
    )
    if not resolved_log_path.exists():
        error_console.print(f"Log file not found: {resolved_log_path}")
        raise typer.Exit(1)

    with resolved_log_path.open(encoding="utf-8") as handle:
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
    raise typer.Exit(_install_browsers())


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


def _read_build_version() -> str | None:
    try:
        from pi_apply._build_info import BUILD_VERSION
    except ImportError:
        return None
    return BUILD_VERSION or None


def _display_version() -> str:
    build_version = _read_build_version()
    if build_version:
        return build_version
    return importlib.metadata.version("pi-apply")


@app.command()
def version() -> None:
    """Print the installed pi-apply build version."""
    try:
        console.print(_display_version())
    except importlib.metadata.PackageNotFoundError as exc:
        error_console.print("pi-apply is not installed as a package")
        raise typer.Exit(1) from exc


if __name__ == "__main__":
    app()
