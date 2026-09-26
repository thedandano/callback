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
import time
import tomllib
from collections.abc import Mapping, Sequence
from contextlib import contextmanager
from pathlib import Path
from typing import Annotated, Any

import typer

from callback import paths, settings
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


@app.callback()
def _load_settings() -> None:
    """Merge ~/.config/callback/env.json into the process env before any command runs.

    Runs ahead of every subcommand (not inside one), so path-resolving code that
    reads os.environ directly (e.g. the server log path) sees settings-file values
    too, not just ones the parent shell happened to export.
    """
    settings.apply_env_file()


SERVER_NAME = "callback"
DEFAULT_LOG_PATH = Path("~/.local/state/callback/server.log").expanduser()
DEFAULT_CLAUDE_CONFIG = Path("~/.claude.json").expanduser()
DEFAULT_CODEX_CONFIG = Path("~/.codex/config.toml").expanduser()
ENV_NAME_RE = re.compile(r"^[A-Z_][A-Z0-9_]*$")
SECRET_ENV_MARKERS = ("KEY", "TOKEN", "SECRET", "PASSWORD")
LANGSMITH_ENV_DEFAULTS = {
    "CALLBACK_TRACE_BACKEND": "langsmith",
    "LANGSMITH_TRACING": "true",
    "LANGSMITH_ENDPOINT": DEFAULT_LANGSMITH_ENDPOINT,
    "LANGSMITH_PROJECT": DEFAULT_LANGSMITH_PROJECT,
}
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


def _read_toml_config(path: Path) -> dict[str, Any]:
    if not path.exists():
        return {}
    text = path.read_text(encoding="utf-8")
    try:
        loaded = tomllib.loads(text)
    except tomllib.TOMLDecodeError as exc:
        raise ConfigError(f"{path} is not valid TOML: {exc}") from exc
    return dict(loaded)


def _warn_if_comments(path: Path) -> None:
    """Say so on stderr before a rewrite drops full-line comments; tomllib cannot keep them."""
    # ponytail: full-line comments only; an inline `# …` after a value is not detected.
    if not path.exists():
        return
    text = path.read_text(encoding="utf-8")
    if any(line.lstrip().startswith("#") for line in text.splitlines()):
        typer.echo(
            f"warning: {path} contains comments; callback rewrites this file "
            "and comments are not preserved",
            err=True,
        )


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


def _is_table_array(value: object) -> bool:
    return (
        isinstance(value, list) and bool(value) and all(isinstance(item, Mapping) for item in value)
    )


def _table_array_lines(
    table_name: str, items: list[Any], prefix: tuple[str, ...], key: str
) -> list[str]:
    lines: list[str] = []
    for item in items:
        lines.append(f"[[{table_name}]]")
        lines.extend(_toml_lines(item, (*prefix, key)))
        lines.append("")
    return lines


def _toml_lines(config: Mapping[str, Any], prefix: tuple[str, ...] = ()) -> list[str]:
    scalar_lines: list[str] = []
    table_lines: list[str] = []

    for key in sorted(config):
        value = config[key]
        table_name = ".".join(_toml_key(part) for part in (*prefix, key))
        if isinstance(value, Mapping):
            table_lines.append(f"[{table_name}]")
            table_lines.extend(_toml_lines(value, (*prefix, key)))
            table_lines.append("")
        elif _is_table_array(value):
            table_lines.extend(_table_array_lines(table_name, value, prefix, key))
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


def _claude_has_legacy_server(path: Path) -> bool:
    config = _read_json_config(path)
    servers = config.get("mcpServers", {})
    if not isinstance(servers, dict):
        raise ConfigError(f'{path} key "mcpServers" must be an object')
    return SERVER_NAME in servers


def _codex_has_legacy_server(path: Path) -> bool:
    config = _read_toml_config(path)
    servers = config.get("mcp_servers", {})
    if not isinstance(servers, dict):
        raise ConfigError(f'{path} key "mcp_servers" must be a table')
    return SERVER_NAME in servers


def _legacy_entry_note(path: Path) -> str:
    """Note text for a `callback` MCP server entry found in a host config.

    Presence alone can't distinguish a leftover duplicate (from the old setup-mcp
    flow, alongside a separate plugin install) from someone's only, correctly
    configured manual registration — so this hedges instead of telling every
    reader to delete their one working entry.
    """
    return (
        f"note: {path} has a callback MCP server entry with an env map set "
        "directly in it. If you also installed callback as a plugin, this may be "
        "a leftover duplicate from the old setup-mcp flow — remove it with "
        "`callback uninstall` if so. If this is your only callback registration "
        f"(e.g. a standalone or uvx install), it's fine to leave as is, though env "
        f"vars now belong in {paths.env_file()} instead."
    )


def _legacy_warning_lines() -> list[str]:
    """Note any `callback` MCP server entries still sitting in a host config."""
    warnings = []
    if _claude_has_legacy_server(DEFAULT_CLAUDE_CONFIG):
        warnings.append(_legacy_entry_note(DEFAULT_CLAUDE_CONFIG))
    if _codex_has_legacy_server(DEFAULT_CODEX_CONFIG):
        warnings.append(_legacy_entry_note(DEFAULT_CODEX_CONFIG))
    return warnings


def _build_status_text(env: Mapping[str, str], *, show_secrets: bool) -> str:
    lines = [f"callback settings ({paths.env_file()})"]
    if not env:
        lines.append("(none)")
        return "\n".join(lines)
    for env_key in sorted(env):
        value = _display_env_value(env_key, env[env_key], show_secrets=show_secrets)
        lines.append(f"{env_key}={value}")
    return "\n".join(lines)


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


def _effective_trace_env() -> dict[str, str]:
    """Merge callback's settings file into a copy of the process env, process values winning."""
    merged: dict[str, str] = dict(os.environ)
    settings.apply_env_file(merged)
    return {key: value for key in LANGSMITH_TRACE_KEYS if (value := merged.get(key))}


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
    paths.write_text_atomic(path, json.dumps(config, indent=2, sort_keys=True) + "\n")


def _remove_server_from_codex(path: Path) -> None:
    if not path.exists():
        return
    _warn_if_comments(path)
    config = _read_toml_config(path)
    servers = config.get("mcp_servers")
    if isinstance(servers, dict):
        servers.pop(SERVER_NAME, None)
    paths.write_text_atomic(path, _dump_toml(config))


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
        typer.echo(
            json.dumps(
                {
                    "event": "cli_serve_log_unavailable",
                    "timestamp": datetime.datetime.now(datetime.UTC).isoformat(),
                    "level": "WARNING",
                    "path": str(resolved_log_path),
                    "error": str(exc),
                }
            ),
            err=True,
        )

    from callback.server import configure_logging, run

    configure_logging(str(resolved_log_path))

    run()


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
    endpoint: Annotated[
        str,
        typer.Option("--endpoint", help="LangSmith API endpoint."),
    ] = DEFAULT_LANGSMITH_ENDPOINT,
    workspace_id: Annotated[
        str | None,
        typer.Option("--workspace-id", help="Optional LangSmith workspace ID."),
    ] = None,
) -> None:
    """Configure LangSmith tracing environment variables in callback's settings file."""
    try:
        env = settings.read_env_file()
    except ValueError as exc:
        typer.echo(f"config langsmith failed: {exc}", err=True)
        raise typer.Exit(1) from exc

    if api_key is None:
        api_key = typer.prompt("LangSmith API key", hide_input=True)
    assert api_key is not None, "typer.prompt always returns a string"

    env.update(LANGSMITH_ENV_DEFAULTS)
    env["LANGSMITH_API_KEY"] = api_key
    env["LANGSMITH_PROJECT"] = project
    env["LANGSMITH_ENDPOINT"] = endpoint
    if workspace_id:
        env["LANGSMITH_WORKSPACE_ID"] = workspace_id
    paths.write_json_atomic(paths.env_file(), env)

    typer.echo(f"Updated LangSmith settings in {paths.env_file()}")
    typer.echo("Restart your MCP host so it reloads the new environment.")
    typer.echo("Use `callback logs --follow` to inspect startup or tracing warnings.")


@config_app.command("status")
def config_status(
    show_secrets: Annotated[
        bool,
        typer.Option("--show-secrets", help="Print secret-like values instead of redacting."),
    ] = False,
) -> None:
    """Show callback's settings file and warn about legacy per-host MCP config entries."""
    try:
        env = settings.read_env_file()
        warnings = _legacy_warning_lines()
    except (ValueError, ConfigError) as exc:
        typer.echo(f"config status failed: {exc}", err=True)
        raise typer.Exit(1) from exc

    typer.echo(_build_status_text(env, show_secrets=show_secrets))
    for warning in warnings:
        typer.echo(warning, err=True)


@env_app.command("set")
def config_env_set(key: str, value: str) -> None:
    """Set one env var override in callback's settings file."""
    try:
        env_key = _validate_env_name(key)
        env = settings.read_env_file()
    except (ConfigError, ValueError) as exc:
        typer.echo(f"config env set failed: {exc}", err=True)
        raise typer.Exit(1) from exc

    env[env_key] = value
    paths.write_json_atomic(paths.env_file(), env)

    typer.echo(f"Set {env_key} in {paths.env_file()}")
    typer.echo("Restart your MCP host so it reloads the new environment.")


@env_app.command("unset")
def config_env_unset(key: str) -> None:
    """Unset one env var override in callback's settings file."""
    try:
        env_key = _validate_env_name(key)
        env = settings.read_env_file()
    except (ConfigError, ValueError) as exc:
        typer.echo(f"config env unset failed: {exc}", err=True)
        raise typer.Exit(1) from exc

    env.pop(env_key, None)
    paths.write_json_atomic(paths.env_file(), env)

    typer.echo(f"Unset {env_key} in {paths.env_file()}")
    typer.echo("Restart your MCP host so it reloads the new environment.")


@env_app.command("list")
def config_env_list(
    show_secrets: Annotated[
        bool,
        typer.Option("--show-secrets", help="Print secret-like values instead of redacting."),
    ] = False,
) -> None:
    """List env var overrides in callback's settings file."""
    try:
        env = settings.read_env_file()
    except ValueError as exc:
        typer.echo(f"config env list failed: {exc}", err=True)
        raise typer.Exit(1) from exc

    if not env:
        typer.echo("(none)")
        return
    for env_key in sorted(env):
        value = _display_env_value(env_key, env[env_key], show_secrets=show_secrets)
        typer.echo(f"{env_key}={value}")


@app.command("trace-check")
def trace_check(
    emit_test_trace: Annotated[
        bool,
        typer.Option("--emit-test-trace", help="Emit one safe LangSmith test trace."),
    ] = False,
) -> None:
    """Verify LangSmith tracing configuration and optional test trace emission."""
    try:
        env = _effective_trace_env()
    except ValueError as exc:
        typer.echo(f"trace-check failed: {exc}", err=True)
        raise typer.Exit(1) from exc

    try:
        project = _check_langsmith_target("env", env, emit_test_trace=emit_test_trace)
    except (ConfigError, TraceCheckError) as exc:
        typer.echo(f"trace-check failed: {_redact_text(str(exc), env)}", err=True)
        raise typer.Exit(1) from exc

    typer.echo(f"env: ok (project: {project})")


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
        typer.echo(f"Log file not found: {resolved_log_path}", err=True)
        raise typer.Exit(1)

    with resolved_log_path.open(encoding="utf-8") as handle:
        entries = handle.readlines()
        for line in entries[-lines:]:
            typer.echo(line.rstrip("\n"))

        if follow:
            while True:
                line = handle.readline()
                if line:
                    typer.echo(line.rstrip("\n"))
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
        typer.echo(f"uninstall failed: {exc}", err=True)
        raise typer.Exit(1) from exc

    if purge:
        for directory in (paths.data_dir(), paths.state_dir()):
            if directory.exists():
                shutil.rmtree(directory)
                typer.echo(f"Deleted: {directory}")


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
        typer.echo(_display_version())
    except importlib.metadata.PackageNotFoundError as exc:
        typer.echo("callback is not installed as a package", err=True)
        raise typer.Exit(1) from exc


def _maybe_install_browsers(*, skip_browsers: bool, print_only: bool) -> None:
    """Install Playwright Chromium unless skipped or in print-only mode."""
    if skip_browsers or print_only:
        return
    typer.echo("Installing Playwright Chromium for callback...")
    returncode = _install_browsers()
    if returncode != 0:
        typer.echo(
            "setup-plugin failed: browser install failed; "
            "run `callback install-browsers` for details",
            err=True,
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
        typer.echo(f"setup-plugin failed: {exc}", err=True)
        raise typer.Exit(1) from exc

    _maybe_install_browsers(skip_browsers=skip_browsers, print_only=print_only)

    try:
        commands = install(targets, source=source, print_only=print_only)
    except PluginInstallError as exc:
        typer.echo(f"setup-plugin failed: {exc}", err=True)
        raise typer.Exit(1) from exc

    prefix = "Would run:" if print_only else "Ran:"
    for cmd in commands:
        typer.echo(f"{prefix} {cmd}")

    typer.echo(
        "Restart the session or run /reload-plugins to load MCP servers. "
        "Note: claude and codex must be on PATH."
    )


if __name__ == "__main__":
    app()
