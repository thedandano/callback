# Codex Marketplace Install Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Make the callback repo installable as a Codex plugin via `codex plugin marketplace add thedandano/callback` + `codex plugin add callback@callback`, with correct commands emitted by `callback setup-plugin --target codex`.

**Architecture:** The repo already ships a Codex plugin manifest (`.codex-plugin/plugin.json`) and a Claude marketplace (`.claude-plugin/marketplace.json`). This plan adds the canonical Codex marketplace manifest at `.agents/plugins/marketplace.json` (Codex docs: repo marketplaces live at `$REPO_ROOT/.agents/plugins/marketplace.json`; `.claude-plugin/marketplace.json` is only a legacy fallback), and fixes `plugin_install.py`, whose Codex commands (`codex marketplace add github:...`) do not match the real Codex CLI (verified against codex-cli 0.142.5: `codex plugin marketplace add <local path | owner/repo[@ref] | git URL>` and `codex plugin add PLUGIN@MARKETPLACE`).

**Tech Stack:** Python 3 / pytest / uv; static JSON manifests; Codex CLI ≥ 0.142.

## Global Constraints

- Verified CLI syntax (codex-cli 0.142.5): `codex plugin marketplace add <SOURCE>` where SOURCE is a local path, `owner/repo[@ref]`, or HTTPS/SSH git URL — there is **no** `github:` prefix and **no** top-level `codex marketplace` subcommand.
- Install command: `codex plugin add callback@callback` (PLUGIN@MARKETPLACE).
- Tests use full-object assertions: `assert actual == expected` with complete dicts/lists, never piecemeal key checks.
- Run `uv run pytest`, `uv run ruff check`, and `uv run pyright` before each commit claim; pre-commit hooks enforce format + coverage.
- Work on a feature branch off `main`; PR targets `main` (no dev branch in this project).
- Plugin/marketplace name pair stays `callback@callback` (matches the Claude marketplace).

---

### Task 0: Branch

- [ ] **Step 1: Create feature branch**

```bash
cd /Users/dandano/workplace/callback
git checkout -b feat/codex-marketplace-install
```

- [ ] **Step 2: Baseline check — does the legacy fallback already work?**

The codex binary's marketplace manifest lookup chain is `.agents/plugins/marketplace.json` → `.agents/plugins/api_marketplace.json` → `.claude-plugin/marketplace.json`. Test the current tree before adding anything:

```bash
codex plugin marketplace add /Users/dandano/workplace/callback
codex plugin list
codex plugin marketplace remove callback
```

Record the result. If the `.claude-plugin` fallback already resolves the `callback` plugin, Task 1's value is the canonical location + explicit policy metadata — state that in the PR description. If the fallback fails, Task 1 is what makes install work at all.

---

### Task 1: Canonical Codex marketplace manifest

**Files:**
- Create: `.agents/plugins/marketplace.json`
- Test: `tests/test_codex_marketplace_manifest.py`

**Interfaces:**
- Consumes: nothing.
- Produces: `.agents/plugins/marketplace.json` — read by `codex plugin marketplace add` when this repo is added as a marketplace source. Task 4 verifies it end-to-end.

- [ ] **Step 1: Write the failing test**

Create `tests/test_codex_marketplace_manifest.py`:

```python
import json
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]


def test_codex_marketplace_manifest_matches_expected():
    manifest = json.loads(
        (REPO_ROOT / ".agents" / "plugins" / "marketplace.json").read_text()
    )
    assert manifest == {
        "name": "callback",
        "plugins": [
            {
                "name": "callback",
                "description": (
                    "Job application MCP workflows: profile onboarding, "
                    "resume tailoring, lead scanning, application review."
                ),
                "source": {"source": "local", "path": "./"},
                "policy": {
                    "installation": "AVAILABLE",
                    "authentication": "ON_INSTALL",
                },
                "category": "Productivity",
            }
        ],
    }


def test_codex_marketplace_description_matches_claude_marketplace():
    codex = json.loads(
        (REPO_ROOT / ".agents" / "plugins" / "marketplace.json").read_text()
    )
    claude = json.loads(
        (REPO_ROOT / ".claude-plugin" / "marketplace.json").read_text()
    )
    assert (
        codex["plugins"][0]["description"] == claude["plugins"][0]["description"]
    )
```

The second test is a drift guard: Codex prefers `.agents/` over the legacy `.claude-plugin/` manifest, so the two copies must not silently diverge.

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest tests/test_codex_marketplace_manifest.py -v`
Expected: FAIL with `FileNotFoundError` (manifest doesn't exist yet).

- [ ] **Step 3: Create the manifest**

Create `.agents/plugins/marketplace.json`:

```json
{
  "name": "callback",
  "plugins": [
    {
      "name": "callback",
      "description": "Job application MCP workflows: profile onboarding, resume tailoring, lead scanning, application review.",
      "source": { "source": "local", "path": "./" },
      "policy": {
        "installation": "AVAILABLE",
        "authentication": "ON_INSTALL"
      },
      "category": "Productivity"
    }
  ]
}
```

Note: `path` is relative to the repo root (mirrors Claude Code, whose `.claude-plugin/marketplace.json` uses `"source": "./"` for the repo root). If Task 4's end-to-end check shows Codex resolving the path relative to the manifest's own directory instead, change `"path"` to `"../../"` in both the manifest and the test, and re-run Task 4. Likewise, if Task 4 rejects the `policy` or `category` values, adjust the manifest and keep the test in lockstep — the full-object test must always mirror the shipped manifest exactly.

- [ ] **Step 4: Run test to verify it passes**

Run: `uv run pytest tests/test_codex_marketplace_manifest.py -v`
Expected: PASS (1 passed).

- [ ] **Step 5: Commit**

```bash
git add .agents/plugins/marketplace.json tests/test_codex_marketplace_manifest.py
git commit -m "feat(plugin): add canonical Codex marketplace manifest"
```

---

### Task 2: Fix Codex CLI commands in `plugin_install.py`

**Files:**
- Modify: `callback/plugin_install.py:61-67` (the `"codex"` entry in `HARNESS_TARGETS`)
- Modify: `tests/test_plugin_install.py:31-36` (`test_default_source_codex_uses_git_ref`)
- Modify: `tests/test_cli.py:1277` and `tests/test_cli.py:1315` (mocked `fake_commands` strings)

**Interfaces:**
- Consumes: existing `HarnessTarget` dataclass and `install()` in `callback/plugin_install.py` (unchanged signatures).
- Produces: `HARNESS_TARGETS["codex"]` emitting `codex plugin marketplace add thedandano/callback` then `codex plugin add callback@callback`. Task 3's README documents exactly these commands.

- [ ] **Step 1: Update the failing test first**

In `tests/test_plugin_install.py`, replace `test_default_source_codex_uses_git_ref` (lines 31–36) with:

```python
def test_default_source_codex_uses_owner_repo_source():
    out = install(resolve_targets("codex"), print_only=True)
    assert out == [
        "codex plugin marketplace add thedandano/callback",
        "codex plugin add callback@callback",
    ]
```

(The rename from `test_default_source_codex_uses_git_ref` reflects that the source is now `owner/repo` shorthand, not a `github:` ref.)

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest tests/test_plugin_install.py::test_default_source_codex_uses_owner_repo_source -v`
Expected: FAIL — actual output is `codex marketplace add github:thedandano/callback`.

- [ ] **Step 3: Fix the codex target**

In `callback/plugin_install.py`, replace the `"codex"` entry in `HARNESS_TARGETS` (lines 61–67) with:

```python
    "codex": HarnessTarget(
        key="codex",
        cli="codex",
        marketplace_add=("plugin", "marketplace", "add"),
        install=("plugin", "add", "callback@callback"),
        default_source="thedandano/callback",
    ),
```

- [ ] **Step 4: Update stale mock strings in `tests/test_cli.py`**

At lines 1277 and 1315, replace:

```python
        "codex marketplace add github:thedandano/callback",
```

with:

```python
        "codex plugin marketplace add thedandano/callback",
```

(These are mocked `fake_commands` return values, so they pass either way — update them so the fixtures match real behavior.)

- [ ] **Step 5: Run the full suite and static checks**

Run: `uv run pytest tests/test_plugin_install.py tests/test_cli.py -v && uv run ruff check && uv run pyright`
Expected: all tests PASS, no lint or type errors.

- [ ] **Step 6: Commit**

```bash
git add callback/plugin_install.py tests/test_plugin_install.py tests/test_cli.py
git commit -m "fix(plugin): emit real Codex CLI marketplace/install commands"
```

---

### Task 3: README Codex install docs

**Files:**
- Modify: `README.md:100-102`

**Interfaces:**
- Consumes: the exact commands produced by Task 2.
- Produces: user-facing install docs; no code depends on this.

- [ ] **Step 1: Update the Codex instructions**

In `README.md`, replace lines 100–102:

```
Restart the client afterward. Codex users can alternatively run
`codex marketplace add github:thedandano/callback` then
`codex plugin add callback@callback`.
```

with:

```
Restart the client afterward. Codex users can alternatively install the
plugin (MCP server + skills) from the repo's built-in marketplace:
`codex plugin marketplace add thedandano/callback` then
`codex plugin add callback@callback` — or run
`callback setup-plugin --target codex`.
```

- [ ] **Step 2: Commit**

```bash
git add README.md
git commit -m "docs(readme): correct Codex plugin install commands"
```

---

### Task 4: End-to-end verification against the real Codex CLI

**Files:** none (verification only; may loop back to Task 1 Step 3's path note).

**Interfaces:**
- Consumes: `.agents/plugins/marketplace.json` from Task 1.
- Produces: verified install path; evidence for the PR description.

- [ ] **Step 1: Add the local clone as a marketplace**

Run: `codex plugin marketplace add /Users/dandano/workplace/callback`
Expected: success output naming the `callback` marketplace. If it errors with "no marketplace manifest found" or resolves zero plugins, apply the `"../../"` path fallback from Task 1 Step 3 and retry.

- [ ] **Step 2: Confirm the plugin is listed**

Run: `codex plugin list`
Expected: a `callback` plugin offered from the `callback` marketplace.

- [ ] **Step 3: Install and inspect**

Run: `codex plugin add callback@callback`
Expected: install succeeds; `~/.codex/config.toml` gains a `[plugins."callback@callback"]` (or equivalent) enabled entry.

- [ ] **Step 4: Clean up the local test install**

```bash
codex plugin remove callback@callback
codex plugin marketplace remove callback
```

Expected: both succeed (check exact selector syntax with `codex plugin remove --help` / `codex plugin marketplace remove --help` if the first form is rejected). Verify `codex plugin list` no longer shows the local marketplace.

- [ ] **Step 5: Full suite + push + PR**

```bash
uv run pytest && uv run ruff check && uv run pyright
git push -u origin feat/codex-marketplace-install
gh pr create --base main --title "feat(plugin): Codex marketplace install support" --body "$(cat <<'EOF'
## Summary
- Add canonical Codex marketplace manifest at `.agents/plugins/marketplace.json`
- Fix `setup-plugin --target codex` to emit real Codex CLI commands (`codex plugin marketplace add`, no `github:` prefix)
- Correct README Codex install instructions

## Verification
- `uv run pytest` green, ruff/pyright clean
- E2E against codex-cli 0.142.5: **local-path** marketplace (`codex plugin marketplace add <clone>`) + `codex plugin add callback@callback` verified, then removed
- The git form (`codex plugin marketplace add thedandano/callback`) fetches GitHub `main`, so it exercises the new `.agents/` manifest only after this PR merges; pre-merge it resolves via the `.claude-plugin` legacy fallback. Post-merge verification is a follow-up step below.

🤖 Generated with [Claude Code](https://claude.com/claude-code)
EOF
)"
```

Expected: PR created targeting `main`.

- [ ] **Step 6 (post-merge follow-up): Verify the git-sourced marketplace**

After the PR merges to `main`:

```bash
codex plugin marketplace add thedandano/callback
codex plugin add callback@callback
codex plugin list
codex plugin remove callback@callback
codex plugin marketplace remove callback
```

Expected: install resolves through the canonical `.agents/plugins/marketplace.json` fetched from GitHub.

---

## Out of scope (deliberate)

- `docs/superpowers/plans/2026-06-22-cross-harness-plugin.md:259` still shows the old `codex marketplace add github:...` syntax and its open question at line 276 is resolved by this plan. Historical plan docs are immutable records — leave it unchanged.
