"""Command-line interface for callback."""

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
from collections.abc import Callable, Mapping, Sequence
from contextlib import contextmanager
from pathlib import Path
from typing import Annotated, Any

import typer
from rich.console import Console
from rich.table import Table

from callback.observability import (
    DEFAULT_LANGSMITH_ENDPOINT,
    DEFAULT_LANGSMITH_PROJECT,
    emit_trace_check_probe,
)
from callback.plugin_install import PluginInstallError, install, resolve_targets

app = typer.Typer(no_args_is_help=True)
config_app = typer.Typer(no_args_is_help=True)
env_app = typer.Typer(no_args_is_help=True)
app.add_typer(config_app, name="config")
config_app.add_typer(env_app, name="env")
console = Console(soft_wrap=True)
error_console = Console(stderr=True, soft_wrap=True)

SERVER_NAME = "callback"
SERVER_COMMAND = "callback"
SERVER_ARGS = ["serve"]
PROJECT_LOG_SERVER_ARGS = ["serve", "--project-logs"]
DEFAULT_LOG_PATH = Path("~/.local/state/callback/server.log").expanduser()
DEFAULT_CLAUDE_CONFIG = Path("~/.claude.json").expanduser()
DEFAULT_CODEX_CONFIG = Path("~/.codex/config.toml").expanduser()
_DATA_DIR = Path("~/.local/share/callback").expanduser()
_STATE_DIR = Path("~/.local/state/callback").expanduser()
ENV_NAME_RE = re.compile(r"^[A-Z_][A-Z0-9_]*$")
SECRET_ENV_MARKERS = ("KEY", "TOKEN", "SECRET", "PASSWORD")
LANGSMITH_ENV_DEFAULTS = {
    "CALLBACK_TRACE_BACKEND": "langsmith",
    "LANGSMITH_TRACING": "true",
    "LANGSMITH_ENDPOINT": DEFAULT_LANGSMITH_ENDPOINT,
    "LANGSMITH_PROJECT": DEFAULT_LANGSMITH_PROJECT,
}
CONFIG_TARGETS = ("claude", "codex", "all")
TRACE_CHECK_TARGETS = ("env", "claude", "codex", "all")
LANGSMITH_TRACE_KEYS = (
    "CALLBACK_TRACE_BACKEND",
    "LANGSMITH_TRACING",
    "LANGSMITH_API_KEY",
    "LANGSMITH_PROJECT",
    "LANGSMITH_ENDPOINT",
    "LANGSMITH_WORKSPACE_ID",
)
TRUE_ENV_VALUES = {"1", "true", "yes", "on"}


class ConfigError(Exception):
    """Raised when an MCP config file cannot be safely updated."""


class TraceCheckError(Exception):
    """Raised when LangSmith trace verification fails."""


def _resolve_command() -> str:
    """Return absolute path to the callback binary, falling back to the bare name."""
    return shutil.which(SERVER_COMMAND) or SERVER_COMMAND


def mcp_server_config(
    command: str | None = None,
    *,
    project_logs: bool = False,
    env: Mapping[str, str] | None = None,
) -> dict[str, object]:
    """Return the launcher config shared by supported MCP clients."""
    args = PROJECT_LOG_SERVER_ARGS if project_logs else SERVER_ARGS
    config: dict[str, object] = {"command": command or SERVER_COMMAND, "args": list(args)}
    if env is not None:
        config["env"] = dict(env)
    return config


def _project_log_path() -> Path:
    return Path.cwd() / ".callback" / "server.log"


def _resolve_log_path(
    log_path: Path | None = None,
    *,
    project_logs: bool = False,
) -> Path:
    """Resolve the audit log path for commands that read or write server logs."""
    if log_path is not None:
        return log_path.expanduser()

    project_log_path = _project_log_path()
    if project_logs:
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


def _coerce_env(value: object) -> dict[str, str] | None:
    """Return a string env map from an existing MCP server entry."""
    if not isinstance(value, Mapping):
        return None
    env = value.get("env")
    if not isinstance(env, Mapping):
        return None
    return {str(key): str(env_value) for key, env_value in env.items()}


def configure_claude(path: Path, command: str | None = None) -> None:
    """Write the Claude MCP server entry, preserving unrelated config keys."""
    config = _read_json_config(path)
    servers = config.setdefault("mcpServers", {})
    if not isinstance(servers, dict):
        raise ConfigError(f'{path} key "mcpServers" must be an object')
    env = _coerce_env(servers.get(SERVER_NAME))
    servers[SERVER_NAME] = mcp_server_config(command, env=env)
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
    env = _coerce_env(servers.get(SERVER_NAME))
    servers[SERVER_NAME] = mcp_server_config(command, env=env)
    _write_text_atomic(path, _dump_toml(config))


def _target_names(target: str) -> tuple[str, ...]:
    normalized = target.strip().lower()
    if normalized == "all":
        return ("claude", "codex")
    if normalized in ("claude", "codex"):
        return (normalized,)
    raise ConfigError(f"target must be one of: {', '.join(CONFIG_TARGETS)}")


def _trace_check_target_names(target: str) -> tuple[str, ...]:
    normalized = target.strip().lower()
    if normalized == "all":
        return ("claude", "codex")
    if normalized in ("env", "claude", "codex"):
        return (normalized,)
    raise TraceCheckError(f"target must be one of: {', '.join(TRACE_CHECK_TARGETS)}")


def _validate_env_name(name: str) -> str:
    normalized = name.strip()
    if not ENV_NAME_RE.match(normalized):
        raise ConfigError(f"invalid env var name: {name}")
    return normalized


def _is_secret_env_name(name: str) -> bool:
    return any(marker in name.upper() for marker in SECRET_ENV_MARKERS)


def _display_env_value(name: str, value: str, *, show_secrets: bool) -> str:
    if show_secrets or not _is_secret_env_name(name):
        return value
    return "********"


def _redact_text(text: str, env: Mapping[str, str]) -> str:
    redacted = text
    for key, value in env.items():
        if value and _is_secret_env_name(key):
            redacted = redacted.replace(value, "********")
    return redacted


def _ensure_claude_server(config: dict[str, Any], path: Path) -> dict[str, Any]:
    servers = config.setdefault("mcpServers", {})
    if not isinstance(servers, dict):
        raise ConfigError(f'{path} key "mcpServers" must be an object')

    server = servers.get(SERVER_NAME)
    if server is None:
        server = mcp_server_config()
        servers[SERVER_NAME] = server
    if not isinstance(server, dict):
        raise ConfigError(f"{path} mcpServers.{SERVER_NAME} must be an object")

    env = server.setdefault("env", {})
    if not isinstance(env, dict):
        raise ConfigError(f"{path} mcpServers.{SERVER_NAME}.env must be an object")
    return env


def _ensure_codex_server(config: dict[str, Any], path: Path) -> dict[str, Any]:
    servers = config.setdefault("mcp_servers", {})
    if not isinstance(servers, dict):
        raise ConfigError(f'{path} key "mcp_servers" must be a table')

    server = servers.get(SERVER_NAME)
    if server is None:
        server = mcp_server_config()
        servers[SERVER_NAME] = server
    if not isinstance(server, dict):
        raise ConfigError(f"{path} mcp_servers.{SERVER_NAME} must be a table")

    env = server.setdefault("env", {})
    if not isinstance(env, dict):
        raise ConfigError(f"{path} mcp_servers.{SERVER_NAME}.env must be a table")
    return env


def _set_claude_env(path: Path, env_updates: Mapping[str, str]) -> None:
    config = _read_json_config(path)
    env = _ensure_claude_server(config, path)
    env.update(env_updates)
    _write_text_atomic(path, json.dumps(config, indent=2, sort_keys=True) + "\n")


def _set_codex_env(path: Path, env_updates: Mapping[str, str]) -> None:
    config = _read_toml_config(path)
    env = _ensure_codex_server(config, path)
    env.update(env_updates)
    _write_text_atomic(path, _dump_toml(config))


def _unset_claude_env(path: Path, key: str) -> None:
    config = _read_json_config(path)
    env = _ensure_claude_server(config, path)
    env.pop(key, None)
    _write_text_atomic(path, json.dumps(config, indent=2, sort_keys=True) + "\n")


def _unset_codex_env(path: Path, key: str) -> None:
    config = _read_toml_config(path)
    env = _ensure_codex_server(config, path)
    env.pop(key, None)
    _write_text_atomic(path, _dump_toml(config))


def _read_claude_env(path: Path) -> dict[str, str]:
    config = _read_json_config(path)
    servers = config.get("mcpServers", {})
    if not isinstance(servers, dict):
        raise ConfigError(f'{path} key "mcpServers" must be an object')
    return _coerce_env(servers.get(SERVER_NAME)) or {}


def _read_codex_env(path: Path) -> dict[str, str]:
    config = _read_toml_config(path)
    servers = config.get("mcp_servers", {})
    if not isinstance(servers, dict):
        raise ConfigError(f'{path} key "mcp_servers" must be a table')
    return _coerce_env(servers.get(SERVER_NAME)) or {}


def _read_process_trace_env() -> dict[str, str]:
    return {key: value for key in LANGSMITH_TRACE_KEYS if (value := os.environ.get(key))}


def _trace_check_env_for_target(
    target: str,
    *,
    claude_path: Path,
    codex_path: Path,
) -> dict[str, str]:
    if target == "env":
        return _read_process_trace_env()
    if target == "claude":
        return _read_claude_env(claude_path)
    return _read_codex_env(codex_path)


def _config_paths(
    *,
    claude_config: Path | None,
    codex_config: Path | None,
) -> dict[str, Path]:
    return {
        "claude": claude_config or DEFAULT_CLAUDE_CONFIG,
        "codex": codex_config or DEFAULT_CODEX_CONFIG,
    }


def _config_env_readers() -> dict[str, Callable[[Path], dict[str, str]]]:
    return {"claude": _read_claude_env, "codex": _read_codex_env}


def _read_config_envs(
    targets: tuple[str, ...],
    paths: Mapping[str, Path],
) -> dict[str, dict[str, str]]:
    readers = _config_env_readers()
    return {target: readers[target](paths[target]) for target in targets}


def _status_for_env_key(
    env_key: str,
    targets: tuple[str, ...],
    envs: Mapping[str, Mapping[str, str]],
) -> str:
    values = [envs[target].get(env_key) for target in targets]
    if any(value is None for value in values):
        return "missing"
    if len(set(values)) == 1:
        return "same"
    return "different"


def _status_cell(
    target_name: str,
    env_key: str | None,
    targets: tuple[str, ...],
    envs: Mapping[str, Mapping[str, str]],
    *,
    show_secrets: bool,
) -> str:
    if target_name not in targets:
        return "not checked"
    if env_key is None:
        return "(none)"
    env = envs[target_name]
    if env_key not in env:
        return "(unset)"
    return _display_env_value(env_key, env[env_key], show_secrets=show_secrets)


def _build_config_status_table(
    targets: tuple[str, ...],
    envs: Mapping[str, Mapping[str, str]],
    *,
    show_secrets: bool,
) -> Table:
    table = Table(title="callback MCP env status")
    table.add_column("env var")
    table.add_column("Claude")
    table.add_column("Codex")
    table.add_column("status")

    env_keys = sorted({env_key for env in envs.values() for env_key in env})
    if not env_keys:
        table.add_row(
            "(none)",
            _status_cell("claude", None, targets, envs, show_secrets=show_secrets),
            _status_cell("codex", None, targets, envs, show_secrets=show_secrets),
            "unset",
        )
        return table

    for env_key in env_keys:
        table.add_row(
            env_key,
            _status_cell("claude", env_key, targets, envs, show_secrets=show_secrets),
            _status_cell("codex", env_key, targets, envs, show_secrets=show_secrets),
            _status_for_env_key(env_key, targets, envs),
        )
    return table


def _env_value_enabled(value: str | None) -> bool:
    return (value or "").strip().lower() in TRUE_ENV_VALUES


def _validate_trace_env(env: Mapping[str, str]) -> None:
    if env.get("CALLBACK_TRACE_BACKEND", "").strip().lower() != "langsmith":
        raise TraceCheckError("CALLBACK_TRACE_BACKEND=langsmith is required")
    if not _env_value_enabled(env.get("LANGSMITH_TRACING")):
        raise TraceCheckError("LANGSMITH_TRACING=true is required")
    if not env.get("LANGSMITH_API_KEY"):
        raise TraceCheckError("LANGSMITH_API_KEY is required")


def _make_langsmith_client(env: Mapping[str, str]):
    from langsmith import Client

    if endpoint := env.get("LANGSMITH_ENDPOINT"):
        return Client(api_key=env["LANGSMITH_API_KEY"], api_url=endpoint)
    return Client(api_key=env["LANGSMITH_API_KEY"])


@contextmanager
def _temporary_trace_env(env: Mapping[str, str]):
    original = {key: os.environ.get(key) for key in LANGSMITH_TRACE_KEYS}
    try:
        for key in LANGSMITH_TRACE_KEYS:
            if key in env:
                os.environ[key] = env[key]
            else:
                os.environ.pop(key, None)
        yield
    finally:
        for key, value in original.items():
            if value is None:
                os.environ.pop(key, None)
            else:
                os.environ[key] = value


def _check_langsmith_target(
    target: str,
    env: Mapping[str, str],
    *,
    emit_test_trace: bool,
) -> str:
    _validate_trace_env(env)
    project = env.get("LANGSMITH_PROJECT") or DEFAULT_LANGSMITH_PROJECT
    with _temporary_trace_env({**env, "LANGSMITH_PROJECT": project}):
        client = _make_langsmith_client(env)
        try:
            next(iter(client.list_projects(limit=1)), None)
        except Exception as exc:
            raise TraceCheckError(str(exc)) from exc
        if emit_test_trace:
            emit_trace_check_probe(
                session_id=f"trace-check-{target}",
                target=target,
                project=project,
            )
    return project


def _set_env_for_targets(
    targets: tuple[str, ...],
    env_updates: Mapping[str, str],
    *,
    claude_path: Path,
    codex_path: Path,
) -> None:
    for target in targets:
        if target == "claude":
            _set_claude_env(claude_path, env_updates)
        else:
            _set_codex_env(codex_path, env_updates)


def _unset_env_for_targets(
    targets: tuple[str, ...],
    key: str,
    *,
    claude_path: Path,
    codex_path: Path,
) -> None:
    for target in targets:
        if target == "claude":
            _unset_claude_env(claude_path, key)
        else:
            _unset_codex_env(codex_path, key)


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
            help="Write logs to .callback/server.log under the current project.",
        ),
    ] = False,
) -> None:
    """Start the callback MCP server."""
    resolved_log_path = _resolve_log_path(log_path, project_logs=project_logs)
    os.environ["CALLBACK_LOG_PATH"] = str(resolved_log_path)
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

    from callback.server import configure_logging, run

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
    """Install callback MCP server entries for Claude and Codex."""
    claude_path = claude_config or DEFAULT_CLAUDE_CONFIG
    codex_path = codex_config or DEFAULT_CODEX_CONFIG
    command = _resolve_command()
    try:
        _validate_claude_config(claude_path)
        _validate_codex_config(codex_path)
        if not skip_browsers:
            console.print("Installing Playwright Chromium for callback...")
            browser_install_returncode = _install_browsers()
            if browser_install_returncode != 0:
                error_console.print(
                    "setup-mcp failed: browser install failed; "
                    "run `callback install-browsers` for details"
                )
                raise typer.Exit(browser_install_returncode)
        configure_claude(claude_path, command)
        configure_codex(codex_path, command)
    except ConfigError as exc:
        error_console.print(f"setup-mcp failed: {exc}")
        raise typer.Exit(1) from exc

    console.print(f"Updated Claude config: {claude_path}")
    console.print(f"Updated Codex config: {codex_path}")
    console.print("Next: run `callback config langsmith` to enable LangSmith tracing.")
    console.print("Then restart your MCP host so Claude or Codex reloads the config.")
    console.print("Use `callback logs --follow` to watch server logs.")


@config_app.command("langsmith")
def config_langsmith(
    api_key: Annotated[
        str | None,
        typer.Option("--api-key", help="LangSmith API key."),
    ] = None,
    project: Annotated[
        str,
        typer.Option("--project", help="LangSmith project name."),
    ] = DEFAULT_LANGSMITH_PROJECT,
    target: Annotated[
        str,
        typer.Option("--target", help="Config target: claude, codex, or all."),
    ] = "all",
    claude_config: Annotated[
        Path | None,
        typer.Option("--claude-config", help="Claude JSON config path."),
    ] = None,
    codex_config: Annotated[
        Path | None,
        typer.Option("--codex-config", help="Codex TOML config path."),
    ] = None,
    endpoint: Annotated[
        str,
        typer.Option("--endpoint", help="LangSmith API endpoint."),
    ] = DEFAULT_LANGSMITH_ENDPOINT,
    workspace_id: Annotated[
        str | None,
        typer.Option("--workspace-id", help="Optional LangSmith workspace ID."),
    ] = None,
) -> None:
    """Configure LangSmith tracing environment variables in MCP host configs."""
    try:
        targets = _target_names(target)
        if api_key is None:
            api_key = typer.prompt("LangSmith API key", hide_input=True)
        env_updates = {
            **LANGSMITH_ENV_DEFAULTS,
            "LANGSMITH_API_KEY": api_key,
            "LANGSMITH_PROJECT": project,
        }
        env_updates["LANGSMITH_ENDPOINT"] = endpoint
        if workspace_id:
            env_updates["LANGSMITH_WORKSPACE_ID"] = workspace_id
        _set_env_for_targets(
            targets,
            env_updates,
            claude_path=claude_config or DEFAULT_CLAUDE_CONFIG,
            codex_path=codex_config or DEFAULT_CODEX_CONFIG,
        )
    except ConfigError as exc:
        error_console.print(f"config langsmith failed: {exc}")
        raise typer.Exit(1) from exc

    console.print(f"Updated LangSmith env for: {', '.join(targets)}")
    console.print("Restart your MCP host so it reloads the new environment.")
    console.print("Use `callback logs --follow` to inspect startup or tracing warnings.")


@config_app.command("status")
def config_status(
    target: Annotated[
        str,
        typer.Option("--target", help="Config target: claude, codex, or all."),
    ] = "all",
    claude_config: Annotated[
        Path | None,
        typer.Option("--claude-config", help="Claude JSON config path."),
    ] = None,
    codex_config: Annotated[
        Path | None,
        typer.Option("--codex-config", help="Codex TOML config path."),
    ] = None,
    show_secrets: Annotated[
        bool,
        typer.Option("--show-secrets", help="Print secret-like values instead of redacting."),
    ] = False,
) -> None:
    """Show callback MCP env status for Claude and Codex."""
    try:
        targets = _target_names(target)
        paths = _config_paths(claude_config=claude_config, codex_config=codex_config)
        envs = _read_config_envs(targets, paths)
    except ConfigError as exc:
        error_console.print(f"config status failed: {exc}")
        raise typer.Exit(1) from exc

    console.print(_build_config_status_table(targets, envs, show_secrets=show_secrets))


@env_app.command("set")
def config_env_set(
    key: str,
    value: str,
    target: Annotated[
        str,
        typer.Option("--target", help="Config target: claude, codex, or all."),
    ] = "all",
    claude_config: Annotated[
        Path | None,
        typer.Option("--claude-config", help="Claude JSON config path."),
    ] = None,
    codex_config: Annotated[
        Path | None,
        typer.Option("--codex-config", help="Codex TOML config path."),
    ] = None,
) -> None:
    """Set one MCP environment variable for callback."""
    try:
        env_key = _validate_env_name(key)
        targets = _target_names(target)
        _set_env_for_targets(
            targets,
            {env_key: value},
            claude_path=claude_config or DEFAULT_CLAUDE_CONFIG,
            codex_path=codex_config or DEFAULT_CODEX_CONFIG,
        )
    except ConfigError as exc:
        error_console.print(f"config env set failed: {exc}")
        raise typer.Exit(1) from exc

    console.print(f"Set {env_key} for: {', '.join(targets)}")
    console.print("Restart your MCP host so it reloads the new environment.")


@env_app.command("unset")
def config_env_unset(
    key: str,
    target: Annotated[
        str,
        typer.Option("--target", help="Config target: claude, codex, or all."),
    ] = "all",
    claude_config: Annotated[
        Path | None,
        typer.Option("--claude-config", help="Claude JSON config path."),
    ] = None,
    codex_config: Annotated[
        Path | None,
        typer.Option("--codex-config", help="Codex TOML config path."),
    ] = None,
) -> None:
    """Unset one MCP environment variable for callback."""
    try:
        env_key = _validate_env_name(key)
        targets = _target_names(target)
        _unset_env_for_targets(
            targets,
            env_key,
            claude_path=claude_config or DEFAULT_CLAUDE_CONFIG,
            codex_path=codex_config or DEFAULT_CODEX_CONFIG,
        )
    except ConfigError as exc:
        error_console.print(f"config env unset failed: {exc}")
        raise typer.Exit(1) from exc

    console.print(f"Unset {env_key} for: {', '.join(targets)}")
    console.print("Restart your MCP host so it reloads the new environment.")


@env_app.command("list")
def config_env_list(
    target: Annotated[
        str,
        typer.Option("--target", help="Config target: claude, codex, or all."),
    ] = "all",
    claude_config: Annotated[
        Path | None,
        typer.Option("--claude-config", help="Claude JSON config path."),
    ] = None,
    codex_config: Annotated[
        Path | None,
        typer.Option("--codex-config", help="Codex TOML config path."),
    ] = None,
    show_secrets: Annotated[
        bool,
        typer.Option("--show-secrets", help="Print secret-like values instead of redacting."),
    ] = False,
) -> None:
    """List callback MCP environment variables."""
    try:
        targets = _target_names(target)
        paths = _config_paths(claude_config=claude_config, codex_config=codex_config)
        readers = _config_env_readers()
        printed = False
        for target_name in targets:
            env = readers[target_name](paths[target_name])
            console.print(f"[{target_name}]", markup=False)
            if not env:
                console.print("(none)")
                continue
            printed = True
            for env_key in sorted(env):
                value = _display_env_value(env_key, env[env_key], show_secrets=show_secrets)
                console.print(f"{env_key}={value}")
        if not printed:
            return
    except ConfigError as exc:
        error_console.print(f"config env list failed: {exc}")
        raise typer.Exit(1) from exc


@app.command("trace-check")
def trace_check(
    target: Annotated[
        str,
        typer.Option("--target", help="Trace target: env, claude, codex, or all."),
    ] = "env",
    emit_test_trace: Annotated[
        bool,
        typer.Option("--emit-test-trace", help="Emit one safe LangSmith test trace."),
    ] = False,
    claude_config: Annotated[
        Path | None,
        typer.Option("--claude-config", help="Claude JSON config path."),
    ] = None,
    codex_config: Annotated[
        Path | None,
        typer.Option("--codex-config", help="Codex TOML config path."),
    ] = None,
) -> None:
    """Verify LangSmith tracing configuration and optional test trace emission."""
    try:
        targets = _trace_check_target_names(target)
    except TraceCheckError as exc:
        error_console.print(f"trace-check failed: {exc}")
        raise typer.Exit(1) from exc

    failures = 0
    for target_name in targets:
        env = _trace_check_env_for_target(
            target_name,
            claude_path=claude_config or DEFAULT_CLAUDE_CONFIG,
            codex_path=codex_config or DEFAULT_CODEX_CONFIG,
        )
        try:
            project = _check_langsmith_target(
                target_name,
                env,
                emit_test_trace=emit_test_trace,
            )
        except (ConfigError, TraceCheckError) as exc:
            failures += 1
            error_console.print(f"{target_name}: failed: {_redact_text(str(exc), env)}")
            continue

        console.print(f"{target_name}: ok (project: {project})")

    if failures:
        raise typer.Exit(1)


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
            help="Read logs from .callback/server.log under the current project.",
        ),
    ] = False,
) -> None:
    """Print the tail of the callback server log."""
    resolved_log_path = _resolve_log_path(
        log_path,
        project_logs=project_logs,
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
    """Remove callback MCP server entries from Claude and Codex configs."""
    claude_path = DEFAULT_CLAUDE_CONFIG
    codex_path = DEFAULT_CODEX_CONFIG
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
    """Upgrade callback to the latest version via uv."""
    result = subprocess.run(["uv", "tool", "upgrade", "callback"])
    raise typer.Exit(result.returncode)


def _read_build_version() -> str | None:
    try:
        from callback._build_info import BUILD_VERSION
    except ImportError:
        return None
    return BUILD_VERSION or None


def _display_version() -> str:
    build_version = _read_build_version()
    if build_version:
        return build_version
    return importlib.metadata.version("callback")


@app.command()
def version() -> None:
    """Print the installed callback build version."""
    try:
        console.print(_display_version())
    except importlib.metadata.PackageNotFoundError as exc:
        error_console.print("callback is not installed as a package")
        raise typer.Exit(1) from exc


def _maybe_install_browsers(*, skip_browsers: bool, print_only: bool) -> None:
    """Install Playwright Chromium unless skipped or in print-only mode."""
    if skip_browsers or print_only:
        return
    console.print("Installing Playwright Chromium for callback...")
    returncode = _install_browsers()
    if returncode != 0:
        error_console.print(
            "setup-plugin failed: browser install failed; "
            "run `callback install-browsers` for details"
        )
        raise typer.Exit(returncode)


@app.command("setup-plugin")
def setup_plugin(
    target: Annotated[str, typer.Option("--target", help="claude | codex | both")] = "both",
    print_only: Annotated[
        bool, typer.Option("--print-only", help="Print commands instead of running them.")
    ] = False,
    skip_browsers: Annotated[
        bool, typer.Option("--skip-browsers", help="Skip Playwright Chromium install.")
    ] = False,
    plugin_source: Annotated[
        Path | None,
        typer.Option(
            "--plugin-source",
            help="Local repo root for development installs. Defaults to GitHub source.",
        ),
    ] = None,
) -> None:
    """Install callback as a plugin for Claude and/or Codex."""
    source: str | None = (
        str(plugin_source.expanduser().resolve()) if plugin_source is not None else None
    )

    try:
        targets = resolve_targets(target)
    except ValueError as exc:
        error_console.print(f"setup-plugin failed: {exc}")
        raise typer.Exit(1) from exc

    _maybe_install_browsers(skip_browsers=skip_browsers, print_only=print_only)

    try:
        commands = install(targets, source=source, print_only=print_only)
    except PluginInstallError as exc:
        error_console.print(f"setup-plugin failed: {exc}")
        raise typer.Exit(1) from exc

    prefix = "Would run:" if print_only else "Ran:"
    for cmd in commands:
        console.print(f"{prefix} {cmd}")

    console.print(
        "Restart the session or run /reload-plugins to load MCP servers. "
        "Note: claude and codex must be on PATH."
    )


if __name__ == "__main__":
    app()
