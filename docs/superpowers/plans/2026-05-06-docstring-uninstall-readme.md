# Docstring Fix + CLI Lifecycle Commands + Version Check + README Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Fix stale module docstring; add `install-browsers`, `uninstall --purge`, and `update` CLI commands; add a browser-install check and update-available notification at server startup; expose `check_update` as an MCP tool; write a complete README.

**Architecture:** Four sequential tasks. Task 1 is a docstring one-liner. Task 2 adds four CLI commands to `cli.py`. Task 3 adds `version_check.py`, wires a startup browser-install check into `run()`, and wires a fire-and-forget version check into the FastMCP lifespan. Task 4 creates `README.md`.

**Tech Stack:** Python 3.12, Typer, subprocess, httpx (explicit dep), packaging.version, FastMCP lifespan, pytest + anyio (transitive, no new dep), Markdown

## Design decisions locked in

- **Tests for `check_update` MCP tool**: `@pytest.mark.anyio` + `FastMCPTransport` in-process client — goes through full MCP protocol stack. `anyio` is already a transitive dep; zero new packages needed.
- **`_ok("", data=...)`**: pass empty string as `session_id` — do not patch the signature. `_ok`/`_err` are eliminated entirely in the planned wiki-ingest cleanup.
- **httpx**: add as explicit dep to `pyproject.toml` (currently transitive only).
- **Version comparison**: `packaging.version.Version(latest.lstrip("v")) > Version(current)` — handles dev builds correctly.
- **Cache**: session-level module global (`_cached: dict | None`), no TTL.
- **Browser check at startup**: `ensure_browsers()` called synchronously in `run()` before `mcp.run()`. Warns and continues on failure — does not crash the server.
- **`ensure_browsers` output**: CLI `install-browsers` passes playwright output through (user sees progress); server auto-check captures stdout/stderr and logs a structured warning only on failure.
- **Lifespan**: used only for the fire-and-forget version check (`asyncio.create_task`). Browser check stays in `run()`.
- **Missing imports to add in `server.py`**: `import asyncio`, `from contextlib import asynccontextmanager`, `from collections.abc import AsyncIterator`.
- **Missing import to add in `cli.py`**: `import sys` (for `sys.executable` in `install-browsers`).

---

## File Map

| File | Action | Reason |
|---|---|---|
| `callback/apply_nodes.py` | Modify lines 1–15 | Replace stale stub docstring |
| `pyproject.toml` | Modify | Add `httpx` to `[project.dependencies]` |
| `callback/cli.py` | Modify | Add `sys` import; `_DATA_DIR`/`_STATE_DIR` constants; `_remove_server_from_*` helpers; `install-browsers`, `uninstall`, `update` commands |
| `tests/test_cli.py` | Modify | Add 7 tests: 1 install-browsers + 5 uninstall + 1 update |
| `callback/version_check.py` | Create | `fetch_latest_tag()`, `check_update()` with session-level cache; `packaging.version` comparison |
| `tests/test_version_check.py` | Create | 4 tests: update available, already current, network error, cached result |
| `callback/server.py` | Modify | Add `asyncio`/`asynccontextmanager`/`AsyncIterator` imports; `import version_check`; `_ensure_browsers()`; `_lifespan` for version check; update `mcp = FastMCP(..., lifespan=_lifespan)`; update `run()` to call `_ensure_browsers()`; add `check_update` MCP tool |
| `tests/test_server.py` | Modify | Add 2 `@pytest.mark.anyio` tests using `FastMCPTransport` in-process client |
| `README.md` | Create | Title, badges, north-star summary, install, install-browsers, update, uninstall, how-to-use |

---

## Task 1: Fix stale docstring in `apply_nodes.py`

**Files:**
- Modify: `callback/apply_nodes.py:1-15`

- [ ] **Step 1: Replace the docstring**

Replace lines 1–15 in `callback/apply_nodes.py` with:

```python
"""Apply graph node implementations.

Ten nodes wired into the linear apply pipeline:
  jd_fetch → keywords_accept → parse_initial → score_initial → tailor
           → render → parse_final → score_final → report → finalize

Each node receives an ApplyState snapshot and returns a dict of state
updates. Nodes do I/O and computation only — no LLM calls.
"""
```

- [ ] **Step 2: Verify pyright still passes**

Run: `uv run pyright`
Expected: `0 errors, 0 warnings, 0 informations`

- [ ] **Step 3: Commit**

```bash
git add callback/apply_nodes.py
git commit -m "docs: replace stale stub docstring in apply_nodes.py"
```

---

## Task 2: Add `install-browsers`, `uninstall`, and `update` CLI commands

**Files:**
- Modify: `pyproject.toml`
- Modify: `callback/cli.py`
- Modify: `tests/test_cli.py`

### 2a — Add httpx as explicit dependency

- [ ] **Step 1: Add httpx to `pyproject.toml`**

In `pyproject.toml`, add `"httpx>=0.27"` to `[project.dependencies]` (after the existing entries):

```toml
dependencies = [
    ...
    "httpx>=0.27",
    ...
]
```

Run: `uv sync`
Expected: exits 0, `uv.lock` updated

- [ ] **Step 2: Commit**

```bash
git add pyproject.toml uv.lock
git commit -m "chore: add httpx as explicit dependency"
```

### 2b — Write the failing tests first

- [ ] **Step 3: Add tests to `tests/test_cli.py`**

Append to `tests/test_cli.py`:

```python
# ── install-browsers ──────────────────────────────────────────────────────


def test_install_browsers_calls_playwright(monkeypatch):
    calls = []

    def fake_run(cmd, **_kwargs):
        calls.append(cmd)
        return type("R", (), {"returncode": 0})()

    monkeypatch.setattr("callback.cli.subprocess.run", fake_run)

    result = runner.invoke(app, ["install-browsers"])

    assert result.exit_code == 0
    assert calls[0][1:] == ["-m", "playwright", "install", "chromium"]


# ── uninstall ─────────────────────────────────────────────────────────────


def test_uninstall_skips_missing_configs(tmp_path):
    result = runner.invoke(
        app,
        [
            "uninstall",
            "--claude-config", str(tmp_path / ".claude.json"),
            "--codex-config",  str(tmp_path / "config.toml"),
        ],
    )
    assert result.exit_code == 0


def test_uninstall_removes_server_entry_from_claude(tmp_path):
    claude_path = tmp_path / ".claude.json"
    configure_claude(claude_path)
    assert "callback" in json.loads(claude_path.read_text())["mcpServers"]

    result = runner.invoke(
        app,
        [
            "uninstall",
            "--claude-config", str(claude_path),
            "--codex-config",  str(tmp_path / "nope.toml"),
        ],
    )

    assert result.exit_code == 0
    assert "callback" not in json.loads(claude_path.read_text()).get("mcpServers", {})


def test_uninstall_removes_server_entry_from_codex(tmp_path):
    codex_path = tmp_path / "config.toml"
    configure_codex(codex_path)
    assert "callback" in _read_toml(codex_path)["mcp_servers"]

    result = runner.invoke(
        app,
        [
            "uninstall",
            "--claude-config", str(tmp_path / "nope.json"),
            "--codex-config",  str(codex_path),
        ],
    )

    assert result.exit_code == 0
    assert "callback" not in _read_toml(codex_path).get("mcp_servers", {})


def test_uninstall_purge_deletes_data_dirs(tmp_path, monkeypatch):
    data_dir  = tmp_path / "share" / "callback"
    state_dir = tmp_path / "state" / "callback"
    data_dir.mkdir(parents=True)
    state_dir.mkdir(parents=True)
    (data_dir / "accomplishments.json").write_text("{}")
    (state_dir / "server.log").write_text("log")

    import callback.cli as cli_mod
    monkeypatch.setattr(cli_mod, "_DATA_DIR",  data_dir)
    monkeypatch.setattr(cli_mod, "_STATE_DIR", state_dir)

    result = runner.invoke(
        app,
        [
            "uninstall",
            "--purge",
            "--claude-config", str(tmp_path / "nope.json"),
            "--codex-config",  str(tmp_path / "nope.toml"),
        ],
    )

    assert result.exit_code == 0
    assert not data_dir.exists()
    assert not state_dir.exists()


def test_uninstall_without_purge_preserves_data_dirs(tmp_path, monkeypatch):
    data_dir  = tmp_path / "share" / "callback"
    state_dir = tmp_path / "state" / "callback"
    data_dir.mkdir(parents=True)
    state_dir.mkdir(parents=True)

    import callback.cli as cli_mod
    monkeypatch.setattr(cli_mod, "_DATA_DIR",  data_dir)
    monkeypatch.setattr(cli_mod, "_STATE_DIR", state_dir)

    runner.invoke(
        app,
        [
            "uninstall",
            "--claude-config", str(tmp_path / "nope.json"),
            "--codex-config",  str(tmp_path / "nope.toml"),
        ],
    )

    assert data_dir.exists()
    assert state_dir.exists()


# ── update ────────────────────────────────────────────────────────────────


def test_update_calls_uv_tool_upgrade(monkeypatch):
    calls = []

    def fake_run(cmd, **_kwargs):
        calls.append(cmd)
        return type("R", (), {"returncode": 0})()

    monkeypatch.setattr("callback.cli.subprocess.run", fake_run)

    result = runner.invoke(app, ["update"])

    assert result.exit_code == 0
    assert calls == [["uv", "tool", "upgrade", "callback"]]
```

- [ ] **Step 4: Run tests — confirm they fail**

Run: `uv run pytest tests/test_cli.py -k "install_browsers or uninstall or update" -v`
Expected: FAIL (commands not yet implemented)

### 2c — Implement the commands

- [ ] **Step 5: Add `import subprocess`, `import sys`, and module-level constants to `callback/cli.py`**

After the existing imports block, add:

```python
import subprocess
import sys
```

After the `DEFAULT_LOG_PATH` line, add:

```python
_DATA_DIR  = Path("~/.local/share/callback").expanduser()
_STATE_DIR = Path("~/.local/state/callback").expanduser()
```

- [ ] **Step 6: Add `install-browsers` command to `callback/cli.py`**

Add after the `setup_mcp` command:

```python
@app.command("install-browsers")
def install_browsers() -> None:
    """Install Playwright browsers required for job-description fetching."""
    result = subprocess.run(
        [sys.executable, "-m", "playwright", "install", "chromium"],
        check=False,
    )
    raise typer.Exit(result.returncode)
```

- [ ] **Step 7: Add helper functions to `callback/cli.py`**

Add these two functions directly after the `configure_codex` function:

```python
def _remove_server_from_claude(path: Path) -> None:
    config = _read_json_config(path)
    servers = config.get("mcpServers", {})
    if isinstance(servers, dict):
        servers.pop(SERVER_NAME, None)
    _write_text_atomic(path, json.dumps(config, indent=2, sort_keys=True) + "\n")


def _remove_server_from_codex(path: Path) -> None:
    config = _read_toml_config(path)
    servers = config.get("mcp_servers", {})
    if isinstance(servers, dict):
        servers.pop(SERVER_NAME, None)
    _write_text_atomic(path, _dump_toml(config))
```

- [ ] **Step 8: Add `uninstall` command to `callback/cli.py`**

Add after the `install-browsers` command:

```python
@app.command()
def uninstall(
    purge: Annotated[
        bool,
        typer.Option("--purge", help="Also delete all callback data and state from disk."),
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
    """Remove callback MCP entries. Pass --purge to also delete all data."""
    import shutil

    claude_path = claude_config or Path("~/.claude.json").expanduser()
    codex_path  = codex_config  or Path("~/.codex/config.toml").expanduser()

    try:
        if claude_path.exists():
            _remove_server_from_claude(claude_path)
            console.print(f"Removed callback from Claude config: {claude_path}")
        if codex_path.exists():
            _remove_server_from_codex(codex_path)
            console.print(f"Removed callback from Codex config: {codex_path}")
    except ConfigError as exc:
        error_console.print(f"uninstall failed: {exc}")
        raise typer.Exit(1) from exc

    if purge:
        for directory in (_DATA_DIR, _STATE_DIR):
            if directory.exists():
                shutil.rmtree(directory)
                console.print(f"Deleted {directory}")
```

- [ ] **Step 9: Add `update` command to `callback/cli.py`**

Add after the `uninstall` command:

```python
@app.command()
def update() -> None:
    """Upgrade callback to the latest release from GitHub."""
    result = subprocess.run(["uv", "tool", "upgrade", "callback"], check=False)
    raise typer.Exit(result.returncode)
```

- [ ] **Step 10: Run the tests — confirm they all pass**

Run: `uv run pytest tests/test_cli.py -v`
Expected: all tests pass, including the 7 new ones

- [ ] **Step 11: Run pyright**

Run: `uv run pyright`
Expected: `0 errors, 0 warnings, 0 informations`

- [ ] **Step 12: Commit**

```bash
git add callback/cli.py tests/test_cli.py
git commit -m "feat(cli): add install-browsers, uninstall (--purge), and update commands"
```

---

## Task 3: Version check — startup notification + MCP tool

**Files:**
- Create: `callback/version_check.py`
- Create: `tests/test_version_check.py`
- Modify: `callback/server.py`
- Modify: `tests/test_server.py`

### 3a — Write failing tests first

- [ ] **Step 1: Create `tests/test_version_check.py`**

```python
"""Tests for version_check.py."""
from __future__ import annotations

import callback.version_check as vc


def test_check_update_returns_update_available(monkeypatch):
    monkeypatch.setattr(vc, "_cached", None)
    monkeypatch.setattr(vc, "fetch_latest_tag", lambda: "v9.9.9")
    monkeypatch.setattr(vc, "_current_version", lambda: "0.2.0")

    result = vc.check_update()

    assert result == {
        "current": "0.2.0",
        "latest": "v9.9.9",
        "update_available": True,
        "checked": True,
    }


def test_check_update_returns_already_current(monkeypatch):
    monkeypatch.setattr(vc, "_cached", None)
    monkeypatch.setattr(vc, "fetch_latest_tag", lambda: "v0.2.0")
    monkeypatch.setattr(vc, "_current_version", lambda: "0.2.0")

    result = vc.check_update()

    assert result == {
        "current": "0.2.0",
        "latest": "v0.2.0",
        "update_available": False,
        "checked": True,
    }


def test_check_update_returns_unchecked_on_network_error(monkeypatch):
    monkeypatch.setattr(vc, "_cached", None)
    monkeypatch.setattr(vc, "fetch_latest_tag", lambda: None)
    monkeypatch.setattr(vc, "_current_version", lambda: "0.2.0")

    result = vc.check_update()

    assert result == {"checked": False}


def test_check_update_uses_cached_result(monkeypatch):
    cached = {"checked": True, "current": "0.2.0", "latest": "v9.9.9", "update_available": True}
    monkeypatch.setattr(vc, "_cached", cached)

    calls = []
    monkeypatch.setattr(vc, "fetch_latest_tag", lambda: calls.append(1) or "v99.0.0")

    result = vc.check_update()

    assert result is cached
    assert calls == []  # no network call made
```

- [ ] **Step 2: Run to confirm failure**

Run: `uv run pytest tests/test_version_check.py -v`
Expected: FAIL — module does not exist yet

### 3b — Add `check_update` MCP tool tests

- [ ] **Step 3: Add tests to `tests/test_server.py`**

`test_server.py` uses `from unittest.mock import patch` already (verify, add if missing). Append these two async tests using the in-process FastMCP client — they go through the full MCP protocol stack:

```python
# ── check_update tool ─────────────────────────────────────────────────────

import pytest
import callback.version_check as _vc
from fastmcp.client import Client
from fastmcp.client.transports import FastMCPTransport


@pytest.mark.anyio
async def test_check_update_tool_returns_update_available(monkeypatch):
    import callback.server as srv

    monkeypatch.setattr(_vc, "_cached", None)
    monkeypatch.setattr(_vc, "fetch_latest_tag", lambda: "v9.9.9")
    monkeypatch.setattr(_vc, "_current_version", lambda: "0.2.0")

    async with Client(FastMCPTransport(srv.mcp)) as client:
        result = await client.call_tool("check_update", {})

    data = json.loads(result.content[0].text)
    assert data["status"] == "ok"
    assert data["data"] == {
        "checked": True,
        "current": "0.2.0",
        "latest": "v9.9.9",
        "update_available": True,
    }


@pytest.mark.anyio
async def test_check_update_tool_returns_already_current(monkeypatch):
    import callback.server as srv

    monkeypatch.setattr(_vc, "_cached", None)
    monkeypatch.setattr(_vc, "fetch_latest_tag", lambda: "v0.2.0")
    monkeypatch.setattr(_vc, "_current_version", lambda: "0.2.0")

    async with Client(FastMCPTransport(srv.mcp)) as client:
        result = await client.call_tool("check_update", {})

    data = json.loads(result.content[0].text)
    assert data["data"]["update_available"] is False
```

- [ ] **Step 4: Run server tests to confirm new ones fail**

Run: `uv run pytest tests/test_server.py -k "check_update" -v`
Expected: FAIL — tool not yet registered

### 3c — Implement

- [ ] **Step 5: Create `callback/version_check.py`**

```python
"""Check whether a newer callback release is available on GitHub."""
from __future__ import annotations

import importlib.metadata
import logging

import httpx
from packaging.version import Version

logger = logging.getLogger(__name__)

_LATEST_URL = "https://api.github.com/repos/thedandano/callback/releases/latest"
_TIMEOUT = 3.0

_cached: dict | None = None


def _current_version() -> str:
    try:
        return importlib.metadata.version("callback")
    except importlib.metadata.PackageNotFoundError:
        return "unknown"


def fetch_latest_tag() -> str | None:
    try:
        resp = httpx.get(_LATEST_URL, timeout=_TIMEOUT, follow_redirects=True)
        resp.raise_for_status()
        return resp.json().get("tag_name")
    except Exception as exc:
        logger.debug("version check failed: %s", exc)
        return None


def check_update() -> dict:
    global _cached
    if _cached is not None:
        return _cached

    latest = fetch_latest_tag()
    if latest is None:
        _cached = {"checked": False}
        return _cached

    current = _current_version()
    try:
        update_available = Version(latest.lstrip("v")) > Version(current)
    except Exception:
        update_available = latest.lstrip("v") != current

    _cached = {
        "checked": True,
        "current": current,
        "latest": latest,
        "update_available": update_available,
    }
    return _cached
```

- [ ] **Step 6: Run version_check tests — confirm they pass**

Run: `uv run pytest tests/test_version_check.py -v`
Expected: 4 tests pass

- [ ] **Step 7: Add `_ensure_browsers`, lifespan, and `check_update` tool to `callback/server.py`**

Add three new stdlib imports at the top of `server.py` (with the existing stdlib imports):

```python
import asyncio
import sys
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
```

Add the `callback` import (with the other `callback` imports):

```python
import callback.version_check as version_check
```

Add `_ensure_browsers` and the lifespan before the `mcp = FastMCP(...)` line:

```python
def _ensure_browsers() -> None:
    result = subprocess.run(
        [sys.executable, "-m", "playwright", "install", "chromium"],
        capture_output=True,
        text=True,
        check=False,
    )
    if result.returncode != 0:
        _log("WARNING", {"event": "browser_install_failed", "stderr": result.stderr})


@asynccontextmanager
async def _lifespan(server: FastMCP) -> AsyncIterator[None]:
    asyncio.create_task(_startup_version_check())
    yield


async def _startup_version_check() -> None:
    info = await asyncio.to_thread(version_check.check_update)
    if info.get("update_available"):
        _log("INFO", {
            "event": "update_available",
            "current": info["current"],
            "latest": info["latest"],
        })
```

Change the `mcp = FastMCP(...)` line to:

```python
mcp = FastMCP("callback", lifespan=_lifespan)
```

Change the `mcp = FastMCP(...)` line to:

```python
mcp = FastMCP("callback", lifespan=_lifespan)
```

Add `subprocess` to the stdlib imports at the top of `server.py` (it is not currently imported):

```python
import subprocess
```

Update `run()` to call `_ensure_browsers()` before starting the server:

```python
def run() -> None:
    """Run the FastMCP stdio server."""
    _ensure_browsers()
    mcp.run()
```

Add the MCP tool in a `# Utility tools` section before `def run()`:

```python
# ── Utility tools ─────────────────────────────────────────────────────────


@mcp.tool()
def check_update() -> str:
    """Check whether a newer version of callback is available.

    Returns current version, latest release tag, and whether an update is
    available. Result is cached for the server session — no repeated network
    calls.
    """
    _log("INFO", {"tool": "check_update"})
    return _ok("", data=version_check.check_update())
```

- [ ] **Step 8: Run all tests**

Run: `uv run pytest -v`
Expected: all tests pass

- [ ] **Step 9: Run pyright**

Run: `uv run pyright`
Expected: `0 errors, 0 warnings, 0 informations`

- [ ] **Step 10: Commit**

```bash
git add callback/version_check.py callback/server.py \
        tests/test_version_check.py tests/test_server.py
git commit -m "feat(server): startup update check + check_update MCP tool"
```

---

## Task 4: Write README.md

**Files:**
- Create: `README.md`

No code under test — documentation only. Visual verification.

- [ ] **Step 1: Create `README.md`** at the repo root:

````markdown
# callback

[![CI](https://github.com/thedandano/callback/actions/workflows/ci.yml/badge.svg)](https://github.com/thedandano/callback/actions/workflows/ci.yml)
[![Python 3.12+](https://img.shields.io/badge/python-3.12%2B-blue)](https://www.python.org/downloads/)

**Get past the ATS gate so you talk to a human recruiter.**

callback is a [LangGraph](https://langchain-ai.github.io/langgraph/) MCP server that tailors
your resume to a job description — honestly, without keyword stuffing or fabricated experience.
It surfaces real gaps between your resume and the JD, scores the result deterministically, and
renders a tailored PDF.

It speaks the [Model Context Protocol](https://modelcontextprotocol.io/): connect it to Claude,
Codex, or any compliant LLM host and drive the workflow through natural language.

---

## Install

**Requirements:** [uv](https://docs.astral.sh/uv/) · Python 3.12+

```bash
uv tool install "callback @ git+https://github.com/thedandano/callback.git"
callback install-browsers     # one-time Chromium setup for JD fetching
callback setup-mcp            # register with Claude and Codex
```

`setup-mcp` writes the server entry to `~/.claude.json` (Claude) and
`~/.codex/config.toml` (Codex). To target a different path:

```bash
callback setup-mcp --claude-config <path> --codex-config <path>
```

---

## Update

```bash
callback update
```

Pulls the latest release from GitHub and upgrades the installed tool in-place.

---

## Uninstall

```bash
callback uninstall          # remove MCP entries; keep your data
callback uninstall --purge  # remove MCP entries AND delete all data
uv tool uninstall callback  # remove the CLI itself
```

Run `callback uninstall` **before** `uv tool uninstall` — once the CLI is gone you
can no longer invoke it.

`--purge` deletes:

| Directory | Contents |
|---|---|
| `~/.local/share/callback/` | Resumes, accomplishments, compiled profile, wiki, application archives |
| `~/.local/state/callback/` | Server logs |

---

## How to use

callback exposes seven MCP tools. Your LLM host calls them in sequence — you drive
the conversation, the tools do the I/O.

### Profile workflow — run once, update as you grow

**`onboard_user`** — Upload your resume. callback extracts sections and saves them to
the profile wiki. Pass `resume_path` (required), optional `skills_path` and
`accomplishments_path` for richer context.

**`create_story`** — Record a STAR accomplishment tied to a skill: `primary_skill`,
`situation`, `behavior`, `impact`. Stories build the evidence layer that scoring draws from.

**`compile_profile`** — Assemble the profile: union of all story skills, orphan detection,
and wiki render. Pass `story_tags` (JSON array) to tag current-JD skills to stories at
compile time.

### Apply workflow — one run per job

**`load_jd`** — Pass a `jd_url` (or raw `jd_text`). Returns JD markdown plus extraction
instructions. Your host LLM extracts structured keywords and calls `submit_keywords`.

**`submit_keywords`** — Submit the validated JDData JSON your host extracted. callback
scores the current resume and waits. Returns `next_action: "submit_tailor"` with the
scoring breakdown and any skill gaps.

**`submit_tailor`** — Submit a list of edits (add/replace/remove bullets, skills, summary).
callback applies them, renders a PDF, re-scores, and returns the before/after delta.
Pass `no_coverage: true` to skip tailoring and finalize with the current resume.

### Utilities

**`get_wiki_pages`** — Read profile wiki pages by ID (e.g. `index.md`,
`experience/<story-id>.md`). Use this to inspect what callback knows about you before tailoring.

**`check_update`** — Check whether a newer release is available. Returns `current`, `latest`,
and `update_available`. Result is cached for the server session. The server also logs a
notification at startup if an update is detected.

```json
{"current": "0.2.0", "latest": "v0.3.0", "update_available": true, "checked": true}
```


---

## Scoring

Scores are deterministic — no LLM, no randomness.

| Dimension | Max | Signal |
|---|---|---|
| KeywordMatch | 45 | Required (0.7) + preferred (0.3) keywords |
| ExperienceFit | 25 | Years met + seniority match |
| ImpactEvidence | 10 | Quantified metric bullets |
| ATSFormat | 10 | Standard section headers present |
| Readability | 10 | Absence of filler phrases |

---

## Development

```bash
uv run pytest                            # unit + integration tests
uv run pyright                           # type check
uv run python scripts/smoke_apply.py    # end-to-end apply smoke
uv run python scripts/smoke_profile.py  # end-to-end profile smoke
```

See [CLAUDE.md](CLAUDE.md) for architecture details and change discipline.
````

- [ ] **Step 2: Verify markdown renders correctly**

Open `README.md` in a markdown previewer and confirm:
- Badges appear on the line after the title
- Install/update/uninstall code blocks render with correct syntax highlighting
- Scoring table columns are aligned

- [ ] **Step 3: Commit**

```bash
git add README.md
git commit -m "docs: add README with install, update, uninstall, and how-to-use"
```

---

## Self-Review

**Spec coverage:**
- [x] Fix stale docstring → Task 1
- [x] `httpx` as explicit dep → Task 2 Step 1
- [x] `install-browsers` command → Task 2 Step 6 + Task 4 README Install
- [x] `uninstall --purge` → Task 2 Steps 7–8 + Task 4 README Uninstall
- [x] `update` command → Task 2 Step 9 + Task 4 README Update
- [x] Browser install check at server startup (`_ensure_browsers` in `run()`) → Task 3 Step 7
- [x] Startup update-available notification (lifespan + `_startup_version_check`) → Task 3 Step 7
- [x] `check_update` MCP tool → Task 3 Step 7
- [x] Package install (GitHub Releases via `uv tool install`) → Task 4 README Install
- [x] Title, badges, North Star summary, How to use → Task 4

**Placeholder scan:** None — all code blocks are complete and runnable.

**Type consistency:** `_DATA_DIR`/`_STATE_DIR` are `Path`; `shutil.rmtree` accepts `Path`.
`subprocess`/`sys` imported at module level in both `cli.py` and `server.py`. `_ok("", data=...)`
passes empty string — `_ok`/`_err` are removed in wiki-ingest cleanup regardless.
`Version(latest.lstrip("v")) > Version(current)` — fallback to string comparison on
`InvalidVersion` (handles dev/unknown installs). `_cached: dict | None` — set once, session-scoped.
`@pytest.mark.anyio` tests use `anyio` transitive dep — no new packages added.
