# Cross-Harness Plugin Packaging — Design + Plan

> **For agentic workers:** REQUIRED SUB-SKILL: superpowers:subagent-driven-development. Steps use checkbox (`- [ ]`) syntax.

**Goal:** Make the callback plugin installable on Claude Code (primary) and Codex (and extensible to other harnesses) via two convergent, non-conflicting paths: native harness CLI, or `callback setup-plugin`.

**Architecture:** One plugin = repo root. Shared body (`skills/`, `commands/`, `.mcp.json`) is read by all harnesses. Thin per-harness manifests + marketplace files are committed in-repo and are the single source of truth both install paths consume. `callback setup-plugin` does NOT hand-write harness state — it shells out to the *same native CLI commands* a user would run (path 2 delegates to path 1), so the two paths converge and stay idempotent.

**Tech Stack:** Python 3.12, Typer, pytest. Pydantic not needed here.

## Why two paths converge

- **Path 1 (native):** `claude plugin marketplace add <repo>` → `claude plugin install callback@callback` (+ Codex equivalents).
- **Path 2 (callback):** `callback setup-plugin` runs those exact commands via subprocess.
- Same marketplace name (`callback`), same source (committed marketplace file), same CLI → re-running either is a no-op/update, never a duplicate. No divergent file-writing.

## Global Constraints

- Plugin name AND Claude marketplace name are both `callback` → install ref is `callback@callback`.
- `setup-plugin` is data-driven over harness targets; default `--target both`; `--print-only` opts out of auto-run. Adding a harness = adding one target descriptor, no new control flow.
- Harness logic lives in a dedicated module `callback/plugin_install.py`; `cli.py` stays a thin command wrapper. One responsibility per file.
- Subprocess execution is injectable (a `runner` callable) so tests never shell out.
- `claude`/`codex` CLI must be on PATH for that target; a missing CLI is an explicit `_err`-style failure, never silent.
- ruff + pyright clean; tests use full-object comparison; commit per task.
- Do NOT commit `.clone_skill_dir/` (scratch) — gitignore it.

## File Structure

| File | Responsibility |
|---|---|
| `.claude-plugin/plugin.json` | Claude manifest (name/version/desc/author/keywords; no path decls — skills/commands/.mcp.json auto-discovered from root) |
| `.claude-plugin/marketplace.json` | Claude marketplace: `{name:"callback", owner, plugins:[{name:"callback", source:"./", description}]}` |
| `.codex-plugin/plugin.json` | Codex manifest (exists) |
| `.agents/plugins/marketplace.json` | Codex repo marketplace (`source:"./"`); needs gitignore un-ignore |
| `.mcp.json`, `skills/`, `commands/` | Shared body (exist) |
| `callback/plugin_install.py` | Harness target descriptors + install/print logic (injectable runner) |
| `callback/cli.py` | `setup-plugin` thin command delegating to `plugin_install` |
| `README.md` | Install section: both harnesses × both paths |

---

### Task 1: Static plugin assets + manifests + gitignore

**Files:**
- Create: `.claude-plugin/plugin.json`, `.claude-plugin/marketplace.json`
- Modify: `.gitignore` (un-ignore `.agents/plugins/marketplace.json`; ignore `.clone_skill_dir/`)
- Create: `.agents/plugins/marketplace.json`
- Fix: `commands/auto-job-apply.md` (currently 0 bytes — give it real frontmatter+body or delete it; deletion preferred if redundant with the `auto-job-apply` skill)
- Commit existing untracked assets: `.codex-plugin/`, `.mcp.json`, `skills/`, `commands/`

**No tests** (static config). Validation step instead.

- [ ] **Step 1:** Write `.claude-plugin/plugin.json`:
```json
{
  "name": "callback",
  "version": "1.0.1",
  "description": "Job application MCP workflows for profile onboarding, resume tailoring, lead scanning, and application review.",
  "author": { "name": "Jane Doe", "url": "https://github.com/thedandano" },
  "homepage": "https://github.com/thedandano/callback",
  "license": "MIT",
  "keywords": ["jobs", "resume", "ats", "mcp", "career"]
}
```

- [ ] **Step 2:** Write `.claude-plugin/marketplace.json`:
```json
{
  "name": "callback",
  "owner": { "name": "Jane Doe" },
  "plugins": [
    {
      "name": "callback",
      "source": "./",
      "description": "Job application MCP workflows: profile onboarding, resume tailoring, lead scanning, application review."
    }
  ]
}
```

- [ ] **Step 3:** Write `.agents/plugins/marketplace.json` (Codex repo marketplace, mirror shape):
```json
{
  "name": "callback",
  "owner": { "name": "Jane Doe" },
  "plugins": [
    {
      "name": "callback",
      "source": "./",
      "description": "Job application MCP workflows: profile onboarding, resume tailoring, lead scanning, application review."
    }
  ]
}
```

- [ ] **Step 4:** Edit `.gitignore`: after the `.agents` line add `!.agents/plugins/` and `!.agents/plugins/marketplace.json` (un-ignore just the committed marketplace), and add `.clone_skill_dir/`.

- [ ] **Step 5:** Fix `commands/auto-job-apply.md` — delete it (the `auto-job-apply` skill already provides the workflow; an empty command file fails `claude plugin validate --strict`). If kept, it must have valid frontmatter + body.

- [ ] **Step 6: Validate**

Run: `uv run pytest -q` (must stay green), then `claude plugin validate ./ --strict` if `claude` is available (else note skipped).
Expected: validation passes; no empty command files.

- [ ] **Step 7: Commit**
```bash
git add -f .agents/plugins/marketplace.json
git add .claude-plugin .codex-plugin .mcp.json skills commands .gitignore
git commit -m "feat: cross-harness plugin manifests (claude + codex) and shared assets"
```

**Interfaces produced:** committed manifests at the paths above; marketplace name `callback`, plugin name `callback`, source `./`.

---

### Task 2: `plugin_install` module (harness targets + install logic)

**Files:**
- Create: `callback/plugin_install.py`
- Test: `tests/test_plugin_install.py`

**Interfaces produced:**
- `HARNESS_TARGETS: dict[str, HarnessTarget]` keyed `"claude"`, `"codex"`.
- `HarnessTarget` (frozen dataclass): `key: str`, `cli: str`, and a method or builder `commands(source: str) -> list[list[str]]` returning argv lists for: marketplace add, then plugin install.
- `resolve_targets(target: str) -> list[HarnessTarget]` — maps `"both"|"claude"|"codex"` to the target list; unknown → `ValueError`.
- `install(targets, source, runner, print_only) -> list[str]` — for each target, builds commands; if `print_only`, returns the command strings; else calls `runner(argv)` (default `subprocess.run`-style, injectable) for each and returns what ran. A non-zero/raising runner result for a target raises `PluginInstallError` naming the target+command (fail fast).

**Source value:** for local install, the repo root path; the marketplace name resolves from the committed marketplace.json `name` (`callback`). Claude install ref = `callback@callback`.

Claude commands (source = repo path):
- `["claude", "plugin", "marketplace", "add", source]`
- `["claude", "plugin", "install", "callback@callback"]`

Codex commands (best-effort, documented; verifier confirms):
- `["codex", "marketplace", "add", source]`
- `["codex", "plugin", "add", "callback@callback"]`

- [ ] **Step 1: Write failing tests** (`tests/test_plugin_install.py`):
```python
import pytest
from callback.plugin_install import (
    HARNESS_TARGETS, PluginInstallError, install, resolve_targets,
)


def test_resolve_both_returns_claude_and_codex():
    keys = [t.key for t in resolve_targets("both")]
    assert keys == ["claude", "codex"]


def test_resolve_single_target():
    assert [t.key for t in resolve_targets("claude")] == ["claude"]


def test_resolve_unknown_raises():
    with pytest.raises(ValueError):
        resolve_targets("emacs")


def test_print_only_returns_commands_without_running():
    ran = []
    out = install(
        resolve_targets("claude"), source="/repo",
        runner=lambda argv: ran.append(argv), print_only=True,
    )
    assert ran == []
    assert out == [
        "claude plugin marketplace add /repo",
        "claude plugin install callback@callback",
    ]


def test_install_runs_each_command_via_runner():
    ran = []
    install(
        resolve_targets("claude"), source="/repo",
        runner=lambda argv: ran.append(argv), print_only=False,
    )
    assert ran == [
        ["claude", "plugin", "marketplace", "add", "/repo"],
        ["claude", "plugin", "install", "callback@callback"],
    ]


def test_runner_failure_raises_plugin_install_error():
    def boom(argv):
        raise OSError("claude not found")
    with pytest.raises(PluginInstallError, match="claude"):
        install(
            resolve_targets("claude"), source="/repo",
            runner=boom, print_only=False,
        )
```

- [ ] **Step 2:** Run `uv run pytest tests/test_plugin_install.py -v` → FAIL (module missing).

- [ ] **Step 3:** Implement `callback/plugin_install.py`. Use a frozen dataclass holding `key`, `cli`, and the two argv templates (with a `{source}` and `{ref}` placeholder or built in a `commands(source)` method). `install` joins argv with spaces for print/return, calls `runner(argv)` otherwise, wraps runner exceptions in `PluginInstallError(f"{target.key}: {' '.join(argv)}: {exc}")`. Keep it data-driven so a new harness is one dict entry.

- [ ] **Step 4:** Run tests → PASS (6 tests).

- [ ] **Step 5:** Lint/type/commit:
```bash
uv run ruff format callback/plugin_install.py tests/test_plugin_install.py
uv run ruff check callback/plugin_install.py tests/test_plugin_install.py
uv run pyright callback/plugin_install.py
git add callback/plugin_install.py tests/test_plugin_install.py
git commit -m "feat: data-driven harness install targets in plugin_install module"
```

---

### Task 3: Refactor `setup-plugin` to delegate (multi-target, --print-only, auto-run)

**Files:**
- Modify: `callback/cli.py` (replace the existing `setup-plugin` command + its private helpers that the new module subsumes; keep `_install_browsers`)
- Test: `tests/test_cli.py` (replace the old `setup_plugin` tests with delegation tests)

**Interfaces consumed:** `callback.plugin_install.{resolve_targets, install, PluginInstallError}`; existing `_install_browsers`.

**Command shape:**
```python
@app.command("setup-plugin")
def setup_plugin(
    target: Annotated[str, typer.Option("--target", help="claude | codex | both")] = "both",
    print_only: Annotated[bool, typer.Option("--print-only", help="Print commands instead of running them.")] = False,
    skip_browsers: Annotated[bool, typer.Option("--skip-browsers", help="Skip Playwright Chromium install.")] = False,
    plugin_source: Annotated[Path | None, typer.Option("--plugin-source", help="Repo root containing the plugin manifests.")] = None,
) -> None:
    """Install callback as a plugin for Claude and/or Codex."""
```
Behavior: resolve `source` (explicit `--plugin-source` or repo root detected by presence of `.claude-plugin/plugin.json`); resolve targets (invalid → error+exit 1); install Chromium unless `--skip-browsers` or `--print-only`; call `install(targets, source, runner=subprocess-runner, print_only=...)`; print each command (run or planned); print the activation reminder ("restart the session or run /reload-plugins to load MCP servers").

- [ ] **Step 1: Write failing tests** in `tests/test_cli.py` (replace old setup_plugin tests). Use the typer CliRunner and monkeypatch `callback.cli.install`/`_install_browsers` or inject. Cover: `--print-only --target claude` prints the two claude commands and runs nothing; `--target both --print-only` prints claude then codex commands; invalid `--target` exits non-zero; `--skip-browsers` path doesn't call `_install_browsers`. Assert against captured output / recorded calls with full comparison where practical.

- [ ] **Step 2:** Run the new tests → FAIL.

- [ ] **Step 3:** Implement: delete the now-dead helpers (`_resolve_plugin_source` stays if still used for source detection; remove `_copy_plugin_bundle`, `_update_plugin_marketplace`, `_marketplace_entry`, `_default_marketplace`, `PLUGIN_BUNDLE_PATHS`, `DEFAULT_PLUGIN_PARENT`, `DEFAULT_MARKETPLACE_PATH` if unused). Wire the command to `plugin_install`.

- [ ] **Step 4:** Run `uv run pytest` → PASS.

- [ ] **Step 5:** Lint/type/commit:
```bash
uv run ruff format callback/cli.py tests/test_cli.py
uv run ruff check callback/cli.py tests/test_cli.py
uv run pyright callback/cli.py
git add callback/cli.py tests/test_cli.py
git commit -m "refactor: setup-plugin delegates to plugin_install (multi-target, --print-only)"
```

---

### Task 4: README install section

**Files:** Modify `README.md`.

- [ ] **Step 1:** Add an "Install as a plugin" section documenting BOTH paths for BOTH harnesses:
  - **Claude — native:** `/plugin marketplace add thedandano/callback` then `/plugin install callback@callback` (and the CLI equivalents `claude plugin marketplace add` / `claude plugin install`).
  - **Claude — callback:** `callback setup-plugin --target claude` (one-shot; `--print-only` to preview).
  - **Codex — native:** `codex marketplace add github:thedandano/callback` then `codex plugin add callback@callback`.
  - **Codex — callback:** `callback setup-plugin --target codex`.
  - **Both:** `callback setup-plugin` (default).
  - Note: restart session / `/reload-plugins` to activate MCP servers; `claude`/`codex` must be on PATH for `setup-plugin`.
- [ ] **Step 2: Commit**
```bash
git add README.md
git commit -m "docs: README install-as-plugin section (native + callback paths, claude + codex)"
```

---

### Task 5: Verification (subagent) — path convergence

Not a code task; the controller dispatches a verification subagent to confirm:
1. Path 1 and Path 2 issue the **same** marketplace name/source and install ref → converge, idempotent, non-conflicting.
2. `.claude-plugin/plugin.json` + `marketplace.json` are schema-valid (`claude plugin validate ./ --strict` if available; else static schema check against the documented fields).
3. Codex command syntax: confirm `codex marketplace add` accepts the chosen source form (local path vs `github:`); if local is unsupported, flag that Codex path-1 needs the git source and update README/target accordingly.
4. No empty command files; `.clone_skill_dir/` is gitignored; `.agents/plugins/marketplace.json` is committed despite the `.agents` ignore.
