# Hermes Plugin Activation Fix Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Make callback's MCP server start through Hermes without regressing Claude, Codex, generic MCP clients, or future Agent Plugins v1 hosts.

**Architecture:** Keep the shared skills in `skills/` and preserve the existing host adapters: Claude reads `.claude-plugin/` plus `.mcp.json`, Codex reads `.codex-plugin/` plus `.mcp.json`, and Hermes or future portable hosts read root `plugin.json` plus `mcp.json`. Fix only the portable `uv` interpreter request, then correct the Hermes-specific discovery instructions.

**Tech Stack:** Agent Plugins v1 JSON, `uv`, pytest, Markdown

**Spec:** `README.md` Hermes Agent installation section and the repository North Star in `AGENTS.md`

## Global Constraints

- Keep callback's supported runtime at Python 3.12 or newer.
- Do not add a native Hermes plugin or another dependency.
- Keep the existing portable `plugin.json`, `skills/`, and `mcp.json` layout.
- Keep `.mcp.json`, `.claude-plugin/plugin.json`, and `.codex-plugin/plugin.json` unchanged.
- Keep every skill host-neutral; do not fork skill content by harness.
- Do not expose invented resume evidence or weaken callback's ATS-honesty rules.

## Review Focus

- A host with Python 3.13 or 3.14 must not be forced to install exactly Python 3.12.
- A host with no Python satisfying `>=3.12` must get `uv`'s explicit interpreter error.
- The MCP command must still run from `${PLUGIN_ROOT}` with development dependencies excluded.
- Claude, Codex, and generic MCP clients must retain the existing `uvx --from git+https://github.com/thedandano/callback callback serve` path.
- The README must not promise the stable namespace `callback:*`; Hermes derives a collision-safe namespace.
- The README must distinguish the CLI's `hermes skills list` from the agent's in-chat `skills_list` tool.

---

### Task 1: Make the portable MCP honor callback's Python range

**Files:**
- Modify: `mcp.json`
- Modify: `tests/test_hermes_plugin_manifest.py`

**Interfaces:**
- Consumes: callback's `requires-python = ">=3.12"` contract from `pyproject.toml`
- Produces: a Hermes stdio command that selects any available interpreter satisfying `>=3.12`
- Preserves: `.mcp.json` as the Claude, Codex, and generic-client launch configuration

- [ ] **Step 1: Change the manifest test first**

Update `test_hermes_mcp_manifest_runs_the_installed_plugin_checkout` to expect:

```python
"args": [
    "run",
    "--python",
    ">=3.12",
    "--no-dev",
    "--project",
    "${PLUGIN_ROOT}",
    "callback",
    "serve",
]
```

Add `test_host_specific_mcp_manifest_remains_uvx_based` in the same file. Assert that `.mcp.json` still contains the existing `uvx --from git+https://github.com/thedandano/callback callback serve` command. This catches an accidental Hermes-only command leaking into Claude, Codex, or generic MCP clients.

- [ ] **Step 2: Run the focused test and confirm it fails**

Run: `uv run pytest tests/test_hermes_plugin_manifest.py tests/test_codex_marketplace_manifest.py tests/test_plugin_install.py -v`

Expected: `test_hermes_mcp_manifest_runs_the_installed_plugin_checkout` fails because `mcp.json` lacks the Python range.

- [ ] **Step 3: Add the interpreter range to `mcp.json`**

Add `"--python", ">=3.12"` immediately after `"run"`. This overrides the exact `.python-version` pin for plugin execution while preserving the package's supported range.

- [ ] **Step 4: Verify the manifest and real startup path**

Run: `uv run pytest tests/test_hermes_plugin_manifest.py -v`

Expected: all tests pass, including the unchanged Claude/Codex `uvx` path.

Run: `timeout 5 uv run --python '>=3.12' --no-dev --project . callback serve`

Expected: callback logs `server_start`; `timeout` then stops the stdio server.

- [ ] **Step 5: Commit**

```bash
git add mcp.json tests/test_hermes_plugin_manifest.py
git commit -m "fix: let Hermes use supported Python runtime"
```

### Task 2: Correct Hermes skill discovery instructions

**Files:**
- Modify: `README.md`

**Interfaces:**
- Consumes: Hermes portable-plugin behavior: plugin skills are omitted from `hermes skills list` and the system prompt, but included by the in-chat `skills_list` tool
- Produces: accurate per-harness install verification and Hermes skill-loading instructions

- [ ] **Step 1: Replace the incorrect namespace claim**

In the Hermes Agent section, explain that:

- `hermes plugins list --plain --no-bundled` verifies installation and enablement.
- `hermes mcp list` does not list portable-plugin MCP entries; verify tools from a fresh chat or with Hermes' plugin activation output.
- The in-chat `skills_list` tool reveals the generated qualified names.
- Users load a returned name with `skill_view("<qualified-name>")`; they must not assume `callback:tailor-resume`.

Leave the Claude, Codex, and generic MCP client commands intact. Add one sentence that the same `skills/` directory is shared across plugin-capable hosts; only discovery names and launch adapters differ.

- [ ] **Step 2: Run documentation and manifest checks**

Run: `uv run pytest tests/test_hermes_plugin_manifest.py tests/test_codex_marketplace_manifest.py tests/test_plugin_install.py tests/test_skills_portable.py -v`

Expected: all tests pass.

- [ ] **Step 3: Run the full project checks**

Run: `uv run pytest`

Expected: all tests pass.

Run: `uv run pyright`

Expected: no errors.

- [ ] **Step 4: Reinstall and verify in Hermes**

Run: `hermes plugins update callback`

Run: `hermes plugins disable callback`

Run: `hermes plugins enable callback`

Start a fresh Hermes chat. Call the in-chat `skills_list` tool and confirm all six callback skills appear under an `agent-plugin-callback-<hash>:` namespace. Ask Hermes to use callback and confirm `mcp__callback__load_jd` is available.

- [ ] **Step 5: Commit**

```bash
git add README.md
git commit -m "docs: explain Hermes plugin discovery"
```
