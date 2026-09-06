# M4 — Shed Weight: Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Ship W3, W5, W6, W7, W8, W9, W10, D5, D8 from `INTENT.md`: cut runtime dependencies from 17 to 11, put every data directory behind one `callback/paths.py`, delete dead and duplicated code, and fix the two small defects that ride along (XDG honored everywhere; `_dump_toml` no longer raises on arrays of tables and says so when it drops comments).

**Architecture:** Purely mechanical. No graph, node, scoring, or tool-envelope behavior changes. One new module (`paths.py`) replaces four copies of `data_dir()` and three hand-rolled atomic JSON writes. Four libraries are swapped for stdlib or already-installed packages (`dataclass-wizard` → pydantic, `rapidfuzz` → `difflib`, `pypdf` → pdfplumber, `httpx` → `urllib`). Two more explicit dependencies go because they were only ever reached through another one (`langchain-core` → `langgraph.types.RunnableConfig`; `rich` → `typer.echo`). Two stateless classes become module functions. The multi-resume branch nobody can reach is deleted.

**Tech Stack:** Python 3.12, pydantic 2, langgraph 1.1, typer, pdfplumber, pytest, uv.

**Spec:** `INTENT.md` §"M4 — Shed weight" plus the D5, D8, W3, W5–W10 rows of its defect and weight tables. Done when: `pyproject.toml` lists at most 11 runtime dependencies, one `paths.py` owns every data directory, and the dormant `[tool.ruff.lint.pylint]` block is gone (ruling below: removed, not enabled).

## Global Constraints

- Tests assert whole objects: build `actual = {...}` and `expected = {...}` and `assert actual == expected`. No piecemeal key checks. The pre-commit hook `expected-object assertions in Python tests` enforces this on `tests/` and `evals/`.
- ruff: line length 100, `max-complexity = 7`. `uv run ruff check .` and `uv run ruff format --check .` clean at every commit.
- `uv run pyright` 0 errors. `uv run pytest -m "not integration and not local" -q` green at every commit (689 at branch start; the count will move as dead tests are deleted and new ones added — record the new number in each task report).
- After any `pyproject.toml` dependency change run `uv sync` and commit `uv.lock` in the same commit.
- Judgement rules from the user's global CLAUDE.md apply: imports at top of file (the only lazy imports allowed are the pre-existing ones in `jd_fetcher.py`, `observability.py`, and `cli.py`'s `langsmith` import); every `except` re-raises, raises with context, or logs at WARNING+; every fallback logs that it was taken.
- Every module reads paths through the module object — `from callback import paths` then `paths.wiki_dir()` — never `from callback.paths import wiki_dir`. Tests patch `callback.paths.<fn>` and that only works when callers resolve the attribute at call time.
- Public MCP tool surface: only `load_jd` changes (its `resume_label` parameter is removed, W5). No other tool signature, envelope key, or `workflow.next_tool` value moves.
- Do not touch scoring weights, tailor instructions, extraction protocol text, or anything under `evals/`.
- Rulings already made (do not re-litigate; record deviations in the task report):
  - **Which 11 dependencies:** `fastmcp`, `jinja2`, `langgraph`, `langgraph-checkpoint-sqlite`, `langsmith`, `pdfplumber`, `playwright`, `pydantic`, `python-docx`, `trafilatura`, `typer`. `langsmith` stays explicit because `tests/test_observability.py::test_langsmith_is_declared_as_direct_dependency` pins it and the code imports it directly. `langchain-core` goes because `langgraph.types` exports `RunnableConfig`. `rich` goes because typer's `echo` covers every use.
  - **PLR09:** the `[tool.ruff.lint.pylint]` block is deleted, not enabled. Enabling it today produces 26 violations (13 PLR0913 too-many-args, 8 PLR0915 too-many-statements, 3 PLR0911 too-many-returns, 2 PLR0912 too-many-branches), 10 of them in `server.py`. Fixing those is M5's "shrink the plumbing" judgment work, not this milestone's mechanical pass. The count is recorded in `INTENT.md` W11 (Task 8).
  - **`runner` injection in `plugin_install.install`** stays. It is the test seam that keeps `subprocess.run` out of the unit tests; W8's target is the `HarnessTarget` dataclass, not the seam.
  - **`WikiStore` class** stays. W8 names `ProfileCompiler` and `WikiRenderer`; `WikiStore` is the path-confinement boundary from M1 (D1) and its methods share `_page_path`.
  - **`ProfileState.resume_label`** stays. W5 targets the `load_jd` tool parameter and the `ambiguous_resume` / `resume_not_found` branches. The profile-side field is M2.5's territory.
  - **Comments in `~/.codex/config.toml`** cannot be preserved without a round-trip TOML library, and adding one contradicts this milestone. D8's fix is: arrays of tables serialize instead of raising, and a warning on stderr names the file when comments are about to be dropped.
- Commit trailer on every commit:
  ```
  Co-Authored-By: Claude Fable 5.1 <noreply@anthropic.com>
  Claude-Session: https://claude.ai/code/session_01CBmQfLDXe6dxY5JVQnvHcz
  ```

## File Structure

| File | Change | Responsibility after M4 |
|---|---|---|
| `callback/paths.py` | **create** | Every data directory (`data_dir`, `state_dir`, `inputs_dir`, `wiki_dir`, `apps_dir`, `apply_db_path`, `profile_db_path`) and the two atomic writers (`write_text_atomic`, `write_json_atomic`). |
| `callback/repository/{accomplishments,preferences,resumes}.py` | modify | Drop their private `data_dir()`; use `paths`. |
| `callback/profilecompiler.py` | modify | Drop `_data_dir`, the hand-rolled atomic write, `rapidfuzz`, and the `ProfileCompiler` class → `compile_profile()` function. |
| `callback/wiki.py` | modify | `BASE_DIR` → `paths.wiki_dir()`; delete `read_index`. |
| `callback/wikirenderer.py` | modify | `WikiRenderer` class → `render_experience_page`, `render_index`, `render_wiki` functions. |
| `callback/apply_graph.py`, `callback/profile_graph.py` | modify | `DB_PATH` constants → `paths.*_db_path()`; `RunnableConfig` from `langgraph.types`. |
| `callback/apply_nodes.py` | modify | `_get_apps_dir` → `paths.apps_dir`; `_normalize_for_match` → `scorer.normalize_for_match`; `_detect_uncovered_skills` uses `SkillsSection.all_skills()`; `finalize` drops `finalized`. |
| `callback/server.py` | modify | `load_jd` loses `resume_label`; `_resolve_resume_label` loses its two unreachable branches; `_all_skills` → `SkillsSection.all_skills()`; `_outcome()` helper; `paths.apps_dir`. |
| `callback/section_map.py` | modify | `SkillsSection.all_skills()`. |
| `callback/scorer.py` | modify | `_normalize_for_match` → public `normalize_for_match`. |
| `callback/state.py` | modify | Delete `ProfileState.wiki_path`, `ProfileState.error`, `ApplyState.finalized`, `TailoredResume.volunteer_raw`. |
| `callback/render/html_builder.py`, `callback/render/resume_template.html.j2` | modify | `pypdf` → pdfplumber page count; delete the volunteer section. |
| `callback/jd_data.py` | modify | `JDData` on pydantic; `dataclass-wizard` gone. |
| `callback/version_check.py` | modify | `httpx` → `urllib.request`; failure logged. |
| `callback/plugin_install.py` | modify | `HarnessTarget` dataclass → plain functions over string keys. |
| `callback/cli.py` | modify | `rich` → `typer.echo`; `_DATA_DIR`/`_STATE_DIR`/`_write_text_atomic` → `paths`; `_toml_lines` handles arrays of tables; comment warning. |
| `callback/observability.py` | modify | `RunnableConfig` from `langgraph.types`. |
| `pyproject.toml`, `uv.lock` | modify | 17 → 11 runtime deps; pylint block deleted. |
| `tests/test_paths.py`, `tests/test_dependencies.py` | **create** | Path resolution + atomic writes; dependency ceiling. |
| `tests/*` (many) | modify | `BASE_DIR` / `_DATA_DIR` patches → `callback.paths.*`; dead-field expectations; W5 tests. |
| `scripts/smoke_apply.py`, `scripts/build_fetch_fixtures.py` | modify | `_get_apps_dir` → `paths.apps_dir`. |
| `CLAUDE.md`, `AGENTS.md`, `README.md`, `skills/*/SKILL.md`, `INTENT.md` | modify | Env vars, module map, `resume_label` mentions, bookkeeping. |

---

### Task 1: `paths.py` owns every data directory (W6, D5)

**Files:**
- Create: `callback/paths.py`
- Modify: `callback/repository/accomplishments.py`, `callback/repository/preferences.py`, `callback/repository/resumes.py`, `callback/profilecompiler.py` (only `_data_dir` and `save_compiled_profile`), `callback/wiki.py` (only `BASE_DIR`/`wiki_root`), `callback/apply_graph.py` (`DB_PATH`), `callback/profile_graph.py` (`DB_PATH`), `callback/apply_nodes.py` (`_get_apps_dir`), `callback/server.py` (line 49 import and line 813), `callback/cli.py` (`_DATA_DIR`, `_STATE_DIR`, `_write_text_atomic`), `scripts/smoke_apply.py`, `scripts/build_fetch_fixtures.py`
- Test: create `tests/test_paths.py`; modify every test that patches `wiki_module.BASE_DIR`, `"callback.wiki.BASE_DIR"`, `callback.cli._DATA_DIR`, `callback.cli._STATE_DIR`, or imports `data_dir` from `callback.repository.resumes` (`tests/test_repository_resumes.py`)

**Interfaces:**
- Produces (used by every later task):
  ```python
  # callback/paths.py
  def data_dir() -> Path          # $XDG_DATA_HOME/callback or ~/.local/share/callback
  def state_dir() -> Path         # ~/.local/state/callback
  def inputs_dir() -> Path        # data_dir()/inputs
  def wiki_dir() -> Path          # data_dir()/profile-wiki
  def apps_dir() -> Path          # $CALLBACK_APPS_DIR or data_dir()/applications
  def apply_db_path() -> Path     # data_dir()/apply-sessions.db
  def profile_db_path() -> Path   # data_dir()/profile-sessions.db
  def write_text_atomic(path: Path, content: str) -> None
  def write_json_atomic(path: Path, data: object) -> None
  ```

- [ ] **Step 1: Write the failing tests**

Create `tests/test_paths.py`:

```python
import json
from pathlib import Path

from callback import paths


def test_data_dir_defaults_under_home(monkeypatch, tmp_path: Path):
    monkeypatch.delenv("XDG_DATA_HOME", raising=False)
    monkeypatch.setattr(Path, "home", staticmethod(lambda: tmp_path))
    actual = {
        "data": paths.data_dir(),
        "inputs": paths.inputs_dir(),
        "wiki": paths.wiki_dir(),
        "apps": paths.apps_dir(),
        "apply_db": paths.apply_db_path(),
        "profile_db": paths.profile_db_path(),
        "state": paths.state_dir(),
    }
    root = tmp_path / ".local" / "share" / "callback"
    expected = {
        "data": root,
        "inputs": root / "inputs",
        "wiki": root / "profile-wiki",
        "apps": root / "applications",
        "apply_db": root / "apply-sessions.db",
        "profile_db": root / "profile-sessions.db",
        "state": tmp_path / ".local" / "state" / "callback",
    }
    assert actual == expected


def test_xdg_data_home_moves_every_data_path(monkeypatch, tmp_path: Path):
    monkeypatch.setenv("XDG_DATA_HOME", str(tmp_path / "xdg"))
    monkeypatch.delenv("CALLBACK_APPS_DIR", raising=False)
    actual = {
        "data": paths.data_dir(),
        "inputs": paths.inputs_dir(),
        "wiki": paths.wiki_dir(),
        "apps": paths.apps_dir(),
        "apply_db": paths.apply_db_path(),
        "profile_db": paths.profile_db_path(),
    }
    root = tmp_path / "xdg" / "callback"
    expected = {
        "data": root,
        "inputs": root / "inputs",
        "wiki": root / "profile-wiki",
        "apps": root / "applications",
        "apply_db": root / "apply-sessions.db",
        "profile_db": root / "profile-sessions.db",
    }
    assert actual == expected


def test_callback_apps_dir_overrides_only_the_archive(monkeypatch, tmp_path: Path):
    monkeypatch.setenv("XDG_DATA_HOME", str(tmp_path / "xdg"))
    monkeypatch.setenv("CALLBACK_APPS_DIR", str(tmp_path / "apps"))
    actual = {"apps": paths.apps_dir(), "wiki": paths.wiki_dir()}
    expected = {"apps": tmp_path / "apps", "wiki": tmp_path / "xdg" / "callback" / "profile-wiki"}
    assert actual == expected


def test_write_text_atomic_creates_parents_and_leaves_no_temp_file(tmp_path: Path):
    target = tmp_path / "nested" / "file.txt"
    paths.write_text_atomic(target, "hello\n")
    actual = {"content": target.read_text(), "entries": sorted(p.name for p in target.parent.iterdir())}
    expected = {"content": "hello\n", "entries": ["file.txt"]}
    assert actual == expected


def test_write_json_atomic_round_trips(tmp_path: Path):
    target = tmp_path / "data.json"
    paths.write_json_atomic(target, {"a": 1, "b": [1, 2]})
    actual = {"parsed": json.loads(target.read_text()), "entries": sorted(p.name for p in tmp_path.iterdir())}
    expected = {"parsed": {"a": 1, "b": [1, 2]}, "entries": ["data.json"]}
    assert actual == expected
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `uv run pytest tests/test_paths.py -q`
Expected: FAIL with `ModuleNotFoundError: No module named 'callback.paths'`

- [ ] **Step 3: Create `callback/paths.py`**

```python
"""Every data directory callback reads or writes, and the atomic writers for them.

XDG_DATA_HOME moves the whole data root. CALLBACK_APPS_DIR moves only the
applications archive. Paths are computed on every call, so an env change or a
test patch takes effect without reloading modules.
"""

from __future__ import annotations

import json
import os
import tempfile
from pathlib import Path


def data_dir() -> Path:
    if xdg_data_home := os.environ.get("XDG_DATA_HOME"):
        return Path(xdg_data_home) / "callback"
    return Path.home() / ".local" / "share" / "callback"


def state_dir() -> Path:
    return Path.home() / ".local" / "state" / "callback"


def inputs_dir() -> Path:
    return data_dir() / "inputs"


def wiki_dir() -> Path:
    return data_dir() / "profile-wiki"


def apps_dir() -> Path:
    if env_path := os.environ.get("CALLBACK_APPS_DIR"):
        return Path(env_path)
    return data_dir() / "applications"


def apply_db_path() -> Path:
    return data_dir() / "apply-sessions.db"


def profile_db_path() -> Path:
    return data_dir() / "profile-sessions.db"


def write_text_atomic(path: Path, content: str) -> None:
    """Write via a sibling temp file and rename, so readers never see a partial file."""
    path.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.NamedTemporaryFile("w", encoding="utf-8", dir=path.parent, delete=False) as tmp:
        tmp.write(content)
        tmp_path = Path(tmp.name)
    tmp_path.replace(path)


def write_json_atomic(path: Path, data: object) -> None:
    write_text_atomic(path, json.dumps(data))
```

- [ ] **Step 4: Run the tests to verify they pass**

Run: `uv run pytest tests/test_paths.py -q`
Expected: 5 passed

- [ ] **Step 5: Point every store at `paths`**

`callback/repository/accomplishments.py`: delete its `data_dir()` and the `import os`; `__init__` uses `paths.data_dir()`; `_save` becomes:

```python
    def _save(self, data: dict) -> None:
        paths.write_json_atomic(self._file_path(), data)
```

`callback/repository/preferences.py`: same shape; `save` becomes `paths.write_json_atomic(self._file_path(), prefs.model_dump())`.

`callback/repository/resumes.py`: delete `data_dir()`; every `dest_dir = data_dir()` becomes `dest_dir = paths.inputs_dir()`.

`callback/profilecompiler.py`: delete `_data_dir` and `import os`; `save_compiled_profile` becomes:

```python
def save_compiled_profile(profile: CompiledProfile, base_dir: Path | None = None) -> None:
    target_dir = base_dir if base_dir is not None else paths.data_dir()
    paths.write_json_atomic(target_dir / _COMPILED_PROFILE_FILE, profile.model_dump())
```

`load_compiled_profile` uses `paths.data_dir()` the same way.

`callback/wiki.py`: delete `BASE_DIR`; `wiki_root` returns `paths.wiki_dir() / resume_label`.

`callback/apply_graph.py` and `callback/profile_graph.py`: delete the `DB_PATH` constant; `build_apply_graph(db_path: Path | None = None)` opens `db_path if db_path is not None else paths.apply_db_path()` (profile: `paths.profile_db_path()`); fix the docstrings that name the default.

`callback/apply_nodes.py`: delete `_get_apps_dir` and its comment; the two callers use `paths.apps_dir()`. Remove `import os` if nothing else uses it.

`callback/server.py`: line 49 stops importing `_get_apps_dir`; line 813 uses `paths.apps_dir()`.

`callback/cli.py`: delete `_DATA_DIR`, `_STATE_DIR`, and `_write_text_atomic`; the purge loop iterates `(paths.data_dir(), paths.state_dir())`; every `_write_text_atomic(` call becomes `paths.write_text_atomic(`. Remove `import tempfile` if unused.

`scripts/smoke_apply.py` and `scripts/build_fetch_fixtures.py`: replace the `_get_apps_dir` import with `from callback import paths` and the calls with `paths.apps_dir()`.

Every touched module imports with `from callback import paths`.

- [ ] **Step 6: Re-point the tests**

Mechanical replacements (use `sed` or a short Python script; check the diff):

| Old | New |
|---|---|
| `monkeypatch.setattr(wiki_module, "BASE_DIR", X)` | `monkeypatch.setattr("callback.paths.wiki_dir", lambda: X)` |
| `monkeypatch.setattr("callback.wiki.BASE_DIR", X)` | `monkeypatch.setattr("callback.paths.wiki_dir", lambda: X)` |
| `patch("callback.cli._DATA_DIR", d)` | `patch("callback.paths.data_dir", lambda: d)` |
| `patch("callback.cli._STATE_DIR", s)` | `patch("callback.paths.state_dir", lambda: s)` |

`tests/test_repository_resumes.py`: replace the `data_dir` import with `from callback import paths`, call `paths.inputs_dir()` where it called `data_dir()`, and keep `test_data_dir_respects_xdg_data_home` asserting the `inputs` path.

`tests/test_wiki.py`: the `store()` helper patches `callback.paths.wiki_dir`.

After the replacements, delete any `import callback.wiki as wiki_module` that ruff reports unused (F401).

- [ ] **Step 7: Verify**

Run: `uv run ruff check . && uv run ruff format --check . && uv run pyright && uv run pytest -m "not integration and not local" -q`
Expected: all clean; pytest green (expect 694: 689 + 5 new).

Also: `grep -rn "local/share\|Path.home()" callback/ scripts/` must return only `callback/paths.py` lines (and `cli.py`'s `DEFAULT_LOG_PATH`, `DEFAULT_CLAUDE_CONFIG`, `DEFAULT_CODEX_CONFIG`, which are config files, not data directories).

- [ ] **Step 8: Commit**

```bash
git add -A
git commit -m "refactor(paths): one module owns every data directory and the atomic writers (W6, D5)"
```

---

### Task 2: `JDData` on pydantic; drop `dataclass-wizard` (W3)

**Files:**
- Modify: `callback/jd_data.py`, `pyproject.toml`, `uv.lock`
- Test: `tests/test_jd_data.py` (must keep passing unchanged except where noted)

**Interfaces:**
- Consumes: nothing from Task 1.
- Produces: `JDData(BaseModel)` with the same field names/defaults; `JDData.model_dump()`; `parse_jd_json(jd_json: str) -> dict` unchanged; `JDDataError(code, message)` unchanged.

- [ ] **Step 1: Run the existing suite as the baseline**

Run: `uv run pytest tests/test_jd_data.py -q`
Expected: green (record the count).

- [ ] **Step 2: Rewrite the model**

Replace the imports and the class in `callback/jd_data.py` (keep `EXTRACTION_PROTOCOL`, `Seniority`, `SUPPORTED_SENIORITIES`, and `JDDataError` exactly as they are):

```python
from typing import Literal

from pydantic import BaseModel, ConfigDict, ValidationError, model_validator
```

```python
_LIST_FIELDS = ("required", "preferred", "key_responsibilities", "required_any", "preferred_any")


def _clean_strings(values: object, field_name: str) -> list[str]:
    if not isinstance(values, list):
        raise JDDataError("invalid_jd", f"{field_name} must be a list")
    cleaned: list[str] = []
    for value in values:
        if not isinstance(value, str):
            raise JDDataError("invalid_jd", f"{field_name} entries must be strings")
        if value.strip():
            cleaned.append(value.strip())
    return cleaned


def _clean_groups(groups: object, field_name: str) -> list[list[str]]:
    if not isinstance(groups, list):
        raise JDDataError("invalid_jd", f"{field_name} must be a list")
    cleaned_groups: list[list[str]] = []
    for group in groups:
        if not isinstance(group, list):
            raise JDDataError("invalid_jd", f"{field_name} entries must be lists")
        cleaned_group = _clean_strings(group, field_name)
        if cleaned_group:
            cleaned_groups.append(cleaned_group)
    return cleaned_groups


class JDData(BaseModel):
    """JSON-compatible JDData contract."""

    model_config = ConfigDict(extra="ignore")

    title: str | None = None
    company: str | None = None
    required: list[str] = []
    preferred: list[str] = []
    required_any: list[list[str]] = []
    preferred_any: list[list[str]] = []
    location: str | None = None
    seniority: Seniority | str = "unspecified"
    required_years: float = 0.0
    team: str | None = None
    key_responsibilities: list[str] = []
    pay_range_min: float | None = None
    pay_range_max: float | None = None

    @model_validator(mode="before")
    @classmethod
    def _clean(cls, data: object) -> object:
        if not isinstance(data, dict):
            raise JDDataError("invalid_jd", "jd_json must encode an object")
        cleaned = dict(data)
        if cleaned.get("seniority") in (None, ""):
            cleaned["seniority"] = "unspecified"
        for field_name in _LIST_FIELDS:
            if not isinstance(cleaned.get(field_name, []), list):
                raise JDDataError("invalid_jd", f"{field_name} must be a list")
        cleaned["required"] = _clean_strings(cleaned.get("required", []), "required")
        cleaned["preferred"] = _clean_strings(cleaned.get("preferred", []), "preferred")
        cleaned["required_any"] = _clean_groups(cleaned.get("required_any", []), "required_any")
        cleaned["preferred_any"] = _clean_groups(cleaned.get("preferred_any", []), "preferred_any")
        if not cleaned["required"] and not cleaned["required_any"]:
            raise JDDataError("invalid_jd", "required or required_any must be non-empty")
        if cleaned["seniority"] not in SUPPORTED_SENIORITIES:
            raise JDDataError("invalid_jd", f"unsupported seniority: {cleaned['seniority']}")
        return cleaned


def parse_jd_json(jd_json: str) -> dict:
    """Parse and validate host-submitted JDData JSON."""
    try:
        return JDData.model_validate_json(jd_json).model_dump()
    except ValidationError as exc:
        raise JDDataError("invalid_jd", f"jd_json parse failed: {exc}") from exc
```

Delete `_load_jd_data`. `JDDataError` is not a `ValueError`, so pydantic lets it propagate out of the validator untouched; `ValidationError` (malformed JSON, wrong scalar types) is translated in `parse_jd_json`.

- [ ] **Step 3: Drop the dependency**

Remove `"dataclass-wizard>=0.39.1",` from `pyproject.toml`; run `uv sync`.

- [ ] **Step 4: Verify**

Run: `uv run pytest tests/test_jd_data.py tests/test_server.py -q && uv run ruff check . && uv run pyright && uv run pytest -m "not integration and not local" -q`
Expected: green. If a test in `tests/test_jd_data.py` constructs `JDData(**...)` with a wrong scalar type and expects `JDDataError`, add `except ValidationError` handling at that construction site is NOT the fix — report it; the ruling is that direct construction may raise `ValidationError` while `parse_jd_json` always raises `JDDataError`.

Also: `grep -rn dataclass_wizard callback tests scripts` returns nothing; `uv run python -c "import dataclass_wizard"` fails.

- [ ] **Step 5: Commit**

```bash
git add -A
git commit -m "refactor(jd_data): JDData on pydantic; drop dataclass-wizard (W3)"
```

---

### Task 3: Drop `rapidfuzz`, `pypdf`, `httpx` (W7)

**Files:**
- Modify: `callback/profilecompiler.py` (fuzzy match), `callback/render/html_builder.py` (page count), `callback/version_check.py` (GET), `pyproject.toml`, `uv.lock`
- Test: `tests/test_profilecompiler.py` (fuzzy expectations), `tests/test_version_check.py` (add one)

**Interfaces:**
- Produces: `profilecompiler._token_sort_ratio(a: str, b: str) -> int` (0–100); `version_check.fetch_latest_tag() -> str | None` unchanged signature.

- [ ] **Step 1: Write the failing tests**

In `tests/test_profilecompiler.py`, delete `from rapidfuzz import fuzz` and replace the two `score = int(fuzz.token_sort_ratio("Kubernetes", "k8s"))` lines with the literal `30` (difflib ratio for `"kubernetes"` vs `"k8s"` is 4/13 → 30 after truncation). Add:

```python
class TestTokenSortRatio:
    def test_order_insensitive_and_case_insensitive(self):
        from callback.profilecompiler import _token_sort_ratio

        actual = {
            "reordered": _token_sort_ratio("REST APIs", "apis rest"),
            "unrelated": _token_sort_ratio("Kubernetes", "k8s"),
            "close": _token_sort_ratio("PostgreSQL", "Postgres"),
        }
        expected = {"reordered": 100, "unrelated": 30, "close": 88}
        assert actual == expected
```

In `tests/test_version_check.py` add:

```python
def test_fetch_latest_tag_returns_none_and_logs_when_request_fails(caplog):
    caplog.set_level("WARNING", logger="callback.version_check")
    with patch.object(vc.urllib.request, "urlopen", side_effect=OSError("offline")):
        tag = vc.fetch_latest_tag()
    actual = {"tag": tag, "warned": any("latest release" in r.message for r in caplog.records)}
    expected = {"tag": None, "warned": True}
    assert actual == expected
```

(The existing tests in that file patch `fetch_latest_tag` itself and need no change.)

- [ ] **Step 2: Run them to verify they fail**

Run: `uv run pytest tests/test_profilecompiler.py tests/test_version_check.py -q`
Expected: FAIL (`_token_sort_ratio` missing; `vc.urllib` missing).

- [ ] **Step 3: Implement**

`callback/profilecompiler.py`: replace `from rapidfuzz import fuzz` with `from difflib import SequenceMatcher` and add:

```python
def _token_sort_ratio(a: str, b: str) -> int:
    """0-100 similarity after lowercasing and sorting whitespace-separated tokens."""
    left = " ".join(sorted(a.lower().split()))
    right = " ".join(sorted(b.lower().split()))
    return int(100 * SequenceMatcher(None, left, right).ratio())
```

In `_lint_story_coverage` use `_token_sort_ratio(primary, s)` and drop the `int(...)` casts (it already returns int).

`callback/render/html_builder.py`: replace `from pypdf import PdfReader` with `import pdfplumber`; line 229 becomes:

```python
        with pdfplumber.open(str(out)) as pdf:
            page_count = len(pdf.pages)
```

`callback/version_check.py`: replace `import httpx` with `import json`, `import logging`, `import urllib.request`; add `logger = logging.getLogger("callback.version_check")`; `fetch_latest_tag` becomes:

```python
def fetch_latest_tag() -> str | None:
    try:
        with urllib.request.urlopen(_LATEST_URL, timeout=3) as response:  # noqa: S310
            return json.load(response).get("tag_name")
    except (OSError, ValueError) as exc:
        # OSError covers URLError/HTTPError/timeouts; ValueError covers bad JSON.
        logger.warning("latest release lookup failed (%s: %s); update status unknown", type(exc).__name__, exc)
        return None
```

(`check_update` already treats `None` as "unknown".)

`pyproject.toml`: remove `"httpx>=0.27",`, `"rapidfuzz>=3.0",`, `"pypdf>=4.0",`; `uv sync`.

- [ ] **Step 4: Verify**

Run: `uv run ruff check . && uv run ruff format --check . && uv run pyright && uv run pytest -m "not integration and not local" -q`
Expected: green. `grep -rn "rapidfuzz\|pypdf\|httpx" callback tests scripts pyproject.toml` returns nothing.

- [ ] **Step 5: Commit**

```bash
git add -A
git commit -m "refactor(deps): difflib, pdfplumber, and urllib replace rapidfuzz, pypdf, httpx (W7)"
```

---

### Task 4: Drop `langchain-core` and `rich`; pin the dependency ceiling

**Files:**
- Modify: `callback/apply_graph.py`, `callback/profile_graph.py`, `callback/observability.py` (import only), `callback/cli.py`, `pyproject.toml`, `uv.lock`
- Test: create `tests/test_dependencies.py`; `tests/test_cli.py` only if it references `callback.cli.console`

**Interfaces:**
- Produces: `cli._build_config_status_text(targets, envs, *, show_secrets) -> str` (replaces `_build_config_status_table`).

- [ ] **Step 1: Write the failing test**

Create `tests/test_dependencies.py`:

```python
import re
import tomllib
from pathlib import Path

_PYPROJECT = Path(__file__).parents[1] / "pyproject.toml"
_MAX_RUNTIME_DEPENDENCIES = 11
_REMOVED = {"crawl4ai", "dataclass-wizard", "httpx", "rapidfuzz", "pypdf", "rich", "langchain-core"}


def _runtime_dependency_names() -> list[str]:
    deps = tomllib.loads(_PYPROJECT.read_text(encoding="utf-8"))["project"]["dependencies"]
    return [re.split(r"[<>=!~\[ ]", dep, maxsplit=1)[0].lower() for dep in deps]


def test_runtime_dependencies_stay_within_the_m4_ceiling():
    names = _runtime_dependency_names()
    actual = {"count_ok": len(names) <= _MAX_RUNTIME_DEPENDENCIES, "removed_present": sorted(_REMOVED & set(names))}
    expected = {"count_ok": True, "removed_present": []}
    assert actual == expected
```

- [ ] **Step 2: Run it to verify it fails**

Run: `uv run pytest tests/test_dependencies.py -q`
Expected: FAIL (`count_ok` False, `rich` and `langchain-core` listed).

- [ ] **Step 3: `RunnableConfig` from langgraph**

In `apply_graph.py`, `profile_graph.py`, `observability.py`: `from langchain_core.runnables import RunnableConfig` → `from langgraph.types import RunnableConfig`.

- [ ] **Step 4: `rich` → `typer.echo`**

In `callback/cli.py`:
- Delete `from rich.console import Console`, `from rich.table import Table`, and the `console` / `error_console` globals.
- `console.print(x)` → `typer.echo(x)`; `error_console.print(x)` → `typer.echo(x, err=True)` (41 sites; `sed` is fine, then read the diff).
- Replace `_build_config_status_table` with:

```python
def _build_config_status_text(
    targets: tuple[str, ...],
    envs: Mapping[str, Mapping[str, str]],
    *,
    show_secrets: bool,
) -> str:
    header = ("env var", "Claude", "Codex", "status")
    env_keys = sorted({env_key for env in envs.values() for env_key in env})
    rows = [
        (
            env_key,
            _status_cell("claude", env_key, targets, envs, show_secrets=show_secrets),
            _status_cell("codex", env_key, targets, envs, show_secrets=show_secrets),
            _status_for_env_key(env_key, targets, envs),
        )
        for env_key in env_keys
    ] or [
        (
            "(none)",
            _status_cell("claude", None, targets, envs, show_secrets=show_secrets),
            _status_cell("codex", None, targets, envs, show_secrets=show_secrets),
            "unset",
        )
    ]
    widths = [max(len(row[i]) for row in (header, *rows)) for i in range(len(header))]
    lines = ["callback MCP env status"]
    for row in (header, *rows):
        lines.append("  ".join(cell.ljust(widths[i]) for i, cell in enumerate(row)).rstrip())
    return "\n".join(lines)
```

  and its caller prints `typer.echo(_build_config_status_text(...))`.
- If `tests/test_cli.py` patches or reads `callback.cli.console` / `error_console`, switch those tests to `result.stdout` / `result.stderr` from `CliRunner`.

- [ ] **Step 5: Drop the dependencies**

Remove `"langchain-core>=1.3.2",` and `"rich>=13.9",` from `pyproject.toml`; `uv sync`. Both packages remain installed transitively (langgraph → langchain-core; fastmcp → rich), so nothing else moves.

- [ ] **Step 6: Verify**

Run: `uv run ruff check . && uv run ruff format --check . && uv run pyright && uv run pytest -m "not integration and not local" -q`
Expected: green; `pyproject.toml` lists exactly 11 dependencies. Also run `uv run callback config status` by hand and paste the output into the report (it should be a plain aligned table).

- [ ] **Step 7: Commit**

```bash
git add -A
git commit -m "refactor(deps): RunnableConfig from langgraph, typer.echo instead of rich; 11 runtime deps"
```

---

### Task 5: Stateless classes become functions (W8)

**Files:**
- Modify: `callback/plugin_install.py`, `callback/cli.py` (lines ~1079–1087), `callback/profilecompiler.py`, `callback/wikirenderer.py`, `callback/profile_nodes.py`
- Test: `tests/test_plugin_install.py`, `tests/test_profilecompiler.py`, `tests/test_wikirenderer.py`

**Interfaces:**
- Produces:
  ```python
  # plugin_install
  DEFAULT_SOURCE = "thedandano/callback"
  def resolve_targets(target: str) -> list[str]                       # ["claude", "codex"] | ["claude"] | ["codex"]
  def commands(target: str, source: str | None = None) -> list[list[str]]
  def install(targets: list[str], source: str | None = None, runner=..., print_only: bool = False) -> list[str]
  # profilecompiler
  def compile_profile(stories: list[CreatedStory], host_tags: list[str]) -> tuple[CompiledProfile, list[str]]
  # wikirenderer
  def render_experience_page(resume_label: str, story: CreatedStory) -> None
  def render_index(resume_label: str, profile: CompiledProfile) -> None
  def render_wiki(resume_label: str, profile: CompiledProfile) -> None   # pages for every story, then the index
  ```

- [ ] **Step 1: Rewrite the tests to the new interfaces**

`tests/test_plugin_install.py`: `[t.key for t in resolve_targets("both")]` → `resolve_targets("both")`; same for the single-target test. Everything else in that file already passes string-keyed targets through `install(...)` and keeps working.

`tests/test_profilecompiler.py`: `ProfileCompiler().compile(stories, host_tags=...)` → `compile_profile(stories, host_tags=...)` (import `compile_profile`).

`tests/test_wikirenderer.py`: delete `_make_store`; each test gets `monkeypatch` and starts with `monkeypatch.setattr("callback.paths.wiki_dir", lambda: tmp_path)`; `WikiRenderer(store=_make_store(tmp_path)).render_experience_page(label, story)` → `render_experience_page(label, story)`; `render_index` likewise. The two tests that built `r1`/`r2` renderers call the function twice.

- [ ] **Step 2: Run them to verify they fail**

Run: `uv run pytest tests/test_plugin_install.py tests/test_profilecompiler.py tests/test_wikirenderer.py -q`
Expected: FAIL on imports/attribute errors.

- [ ] **Step 3: Implement**

`callback/plugin_install.py` (whole module body after the error class and `_subprocess_runner`):

```python
DEFAULT_SOURCE = "thedandano/callback"
_INSTALL_ARGS: dict[str, tuple[str, ...]] = {
    "claude": ("plugin", "install", "callback@callback"),
    "codex": ("plugin", "add", "callback@callback"),
}


def resolve_targets(target: str) -> list[str]:
    """"both" → ["claude", "codex"]; a known key → [key]; anything else raises ValueError."""
    if target == "both":
        return list(_INSTALL_ARGS)
    if target in _INSTALL_ARGS:
        return [target]
    raise ValueError(f"Unknown target: {target}")


def commands(target: str, source: str | None = None) -> list[list[str]]:
    """Marketplace-add then plugin-install argv lists for one harness."""
    return [
        [target, "plugin", "marketplace", "add", source or DEFAULT_SOURCE],
        [target, *_INSTALL_ARGS[target]],
    ]


def install(
    targets: list[str],
    source: str | None = None,
    runner: Callable[[list[str]], None] = _subprocess_runner,
    print_only: bool = False,
) -> list[str]:
    """Run (or, with print_only, just list) the install commands for each target."""
    executed: list[str] = []
    for target in targets:
        for argv in commands(target, source):
            cmd_str = " ".join(argv)
            if not print_only:
                try:
                    runner(argv)
                except (OSError, subprocess.CalledProcessError) as exc:
                    raise PluginInstallError(f"{target}: {cmd_str}: {exc}") from exc
            executed.append(cmd_str)
    return executed
```

Delete `HarnessTarget`, `HARNESS_TARGETS`, and the `dataclass` import. In `cli.py` the `install` command already passes `resolve_targets(target)` straight into `install(...)`; if it reads `.key` anywhere, use the string.

`callback/profilecompiler.py`: turn `ProfileCompiler.compile` into a module function `compile_profile(stories, host_tags)` with the same body; delete the class.

`callback/wikirenderer.py`: delete `WikiRenderer` and `_WIKI_STORE`; add:

```python
def render_experience_page(resume_label: str, story: CreatedStory) -> None:
    WikiStore().write_experience_page(resume_label, company_slug(story.id), _experience_page_content(story))


def render_index(resume_label: str, profile: CompiledProfile) -> None:
    WikiStore().write_index(resume_label, _index_content(profile))


def render_wiki(resume_label: str, profile: CompiledProfile) -> None:
    for story in profile.stories:
        render_experience_page(resume_label, story)
    render_index(resume_label, profile)
```

`callback/profile_nodes.py`: delete `_render_wiki`; `compile_profile` node calls `compile_profile(stories, all_tags)` (rename the import if the node function is also called `compile_profile` — import the module function as `from callback.profilecompiler import compile_profile as build_profile` to avoid shadowing) and `render_wiki(label, profile)`.

- [ ] **Step 4: Verify**

Run: `uv run ruff check . && uv run ruff format --check . && uv run pyright && uv run pytest -m "not integration and not local" -q`
Expected: green. `grep -rn "HarnessTarget\|ProfileCompiler\|WikiRenderer" callback tests scripts` returns nothing.

- [ ] **Step 5: Commit**

```bash
git add -A
git commit -m "refactor: HarnessTarget, ProfileCompiler, WikiRenderer become plain functions (W8)"
```

---

### Task 6: Dead code and duplicates (W9, W5, W10)

**Files:**
- Modify: `callback/state.py`, `callback/apply_nodes.py`, `callback/render/html_builder.py`, `callback/render/resume_template.html.j2`, `callback/wiki.py`, `callback/server.py`, `callback/section_map.py`, `callback/scorer.py`, `callback/profile_nodes.py`, `pyproject.toml`
- Test: `tests/test_state.py`, `tests/test_score_roundtrip.py`, `tests/test_apply_e2e.py`, `tests/test_observability.py`, `tests/test_wiki.py`, `tests/test_server_profile.py`, `tests/test_server.py`, `tests/test_section_map.py`, `tests/test_render.py` (if it references volunteer)

**Interfaces:**
- Produces: `SkillsSection.all_skills() -> list[str]` (flat first, then every category in order); `scorer.normalize_for_match(text) -> str` (public; same body as the old `_normalize_for_match`); `server._outcome(final: dict) -> dict`; `server._resolve_resume_label(session_id) -> tuple[str | None, str | None]`; `load_jd(jd_url=None, jd_raw_text=None)`.

- [ ] **Step 1: Write the failing tests**

`tests/test_section_map.py` — add:

```python
def test_all_skills_flat_then_categorized_in_order():
    section = SkillsSection(flat=["Go"], categorized={"Cloud": ["AWS", "GCP"], "Data": ["Pandas"]})
    assert section.all_skills() == ["Go", "AWS", "GCP", "Pandas"]
```

`tests/test_server.py` — delete `test_load_jd_returns_ambiguous_resume_error_for_multiple_resumes` and the `resume_not_found` test near line 1499. Replace with one test in the same style as its neighbours (reuse their fixtures/patches for `list_resumes`):

```python
def test_load_jd_uses_first_registered_resume_and_warns_when_several(caplog):
    caplog.set_level("WARNING", logger="callback.server")
    with patch("callback.server.list_resumes", return_value=["a", "b"]):
        resolved, err = server._resolve_resume_label("sess-1")
    actual = {"resolved": resolved, "err": err, "warned": any("multiple resumes" in r.message for r in caplog.records)}
    expected = {"resolved": "a", "err": None, "warned": True}
    assert actual == expected
```

(Adjust the patch target and the logger name to match how `server.py` actually imports `list_resumes` and logs — read the file first; `_log("WARNING", {...})` is the existing pattern, and its logger name is whatever `server.py` builds. The assertion must be on the warning reaching a log record.)

`tests/test_state.py`: remove `"finalized"` from the `ApplyState` field set and `"wiki_path"` / `"error"` from the `ProfileState` set; delete `test_field_types_finalized`; drop `finalized=False` from the constructor call near line 192 and the `assert state.finalized is False` line.

`tests/test_score_roundtrip.py:183`: `assert result == {"finalized_at": result["finalized_at"]}`.

`tests/test_apply_e2e.py`: line 189 `expected_keys = {"finalized_at", "pdf_path", "score_initial", "score_final"}`; lines 241/247 use `"finalized": state.get("finalized_at") is not None` with expected `True`.

`tests/test_observability.py:919`: delete the `"wiki_path": None,` line (and any `"error": None` for a ProfileState summary in the same dict).

`tests/test_wiki.py::test_write_read_index_round_trip`: `assert s.read_pages("my-resume", ["index.md"]) == {"index.md": content}`.

`tests/test_server_profile.py:617`: `wiki_module.WikiStore().read_pages("backend", ["index.md"])["index.md"]`.

- [ ] **Step 2: Run them to verify they fail**

Run: `uv run pytest tests/test_section_map.py tests/test_server.py tests/test_state.py -q`
Expected: FAIL (`all_skills` missing; state fields still present; `_resolve_resume_label` signature).

- [ ] **Step 3: Implement W9 (dead code)**

- `callback/state.py`: delete `TailoredResume.volunteer_raw`, `ApplyState.finalized`, `ProfileState.wiki_path`, `ProfileState.error`.
- `callback/apply_nodes.py::finalize`: return `{"finalized_at": finalized_at}`; update the docstring ("Sets finalized=True" goes).
- `callback/render/html_builder.py`: delete the `volunteer_entries=` kwarg. `callback/render/resume_template.html.j2`: delete the whole `{% if volunteer_entries %} … {% endif %}` section.
- `callback/wiki.py`: delete `read_index`.
- `pyproject.toml`: delete the `[tool.ruff.lint.pylint]` block (three keys). Leave `[tool.ruff.lint.mccabe]`.
- `grep -rn "finalized\b\|wiki_path\|volunteer\|read_index" callback` must return only `finalized_at` hits.

- [ ] **Step 4: Implement W5 (multi-resume plumbing)**

`callback/server.py`:
- `load_jd(jd_url: str | None = None, jd_raw_text: str | None = None)`; drop the `resume_label` paragraph and arg from its docstring; drop `resume_label=` from the `_load_jd_impl` call and from `_load_jd_impl`'s own signature.
- `_resolve_resume_label(session_id: str)`:

```python
def _resolve_resume_label(session_id: str) -> tuple[str | None, str | None]:
    """Return (label, None) for the registered resume, or (None, error envelope)."""
    registered = list_resumes()
    if not registered:
        return None, _err(
            stage="load_jd",
            code="no_resume_registered",
            message="no resume registered; run onboard_user first",
            session_id=session_id,
            retriable=False,
        )
    if len(registered) > 1:
        _log("WARNING", {"tool": "load_jd", "session_id": session_id, "event": "multiple resumes registered; using first", "registered": registered})
    return registered[0], None
```

  (Use the module's existing `_log` helper; the message must contain "multiple resumes".)
- Remove the now-unused `ambiguous_resume` / `resume_not_found` branches. `observability.py`'s `resume_label` metadata key stays: the resolved label is still session metadata.

- [ ] **Step 5: Implement W10 (duplicates)**

- `callback/section_map.py::SkillsSection`:

```python
    def all_skills(self) -> list[str]:
        """Every skill string: the flat list first, then each category in order."""
        result = list(self.flat)
        for items in self.categorized.values():
            result.extend(items)
        return result
```

- `callback/apply_nodes.py::_detect_uncovered_skills`: `all_skills = section_map.skills.all_skills()`.
- `callback/profile_nodes.py::_resume_skills`: return `section_map.skills.all_skills()`.
- `callback/server.py`: delete `_all_skills`; `_detect_orphaned_required` uses `SkillsSection.model_validate(sections.get("skills") or {}).all_skills()` (import `SkillsSection` from `callback.section_map`).
- `callback/scorer.py`: rename `_normalize_for_match` → `normalize_for_match` (all four internal call sites). `callback/server.py` lines 232/235 call `scorer.normalize_for_match`. `callback/apply_nodes.py`: delete its own `_normalize_for_match` and use `normalize_for_match` imported from `callback.scorer`; delete `_DASH_RE` / `_WS_RE` from `apply_nodes.py` if nothing else there uses them (ruff will tell you). The one behavioral difference — scorer's version also collapses whitespace around `/` — is accepted; `tests/test_server.py::test_suggested_alternatives_uses_normalization` must still pass.
- `callback/server.py`: add

```python
def _outcome(final: dict) -> dict:
    if (final.get("report") or {}).get("no_coverage"):
        return {"no_coverage": True, "reason": "no wiki stories cover required keywords"}
    return {"no_coverage": False, "reason": None}
```

  and use `"outcome": _outcome(final)` at both sites (≈ lines 1088 and 1224).

- [ ] **Step 6: Verify**

Run: `uv run ruff check . && uv run ruff format --check . && uv run pyright && uv run pytest -m "not integration and not local" -q`
Expected: green. `uv run ruff check --select PLR09 callback | tail -1` still reports 26 (nothing here is meant to fix them; the block is simply gone from config).

- [ ] **Step 7: Commit**

```bash
git add -A
git commit -m "refactor: delete dead fields, the unreachable multi-resume branch, and three duplicates (W9, W5, W10)"
```

---

### Task 7: `_dump_toml` handles arrays of tables and warns before dropping comments (D8)

**Files:**
- Modify: `callback/cli.py` (`_toml_lines`, `_read_toml_config`)
- Test: `tests/test_cli.py`

**Interfaces:**
- Produces: `_read_toml_config(path) -> dict` unchanged signature; `_dump_toml(config) -> str` unchanged signature.

- [ ] **Step 1: Write the failing tests**

Add to `tests/test_cli.py` (next to the other `configure_codex` tests; reuse `_read_toml`):

```python
def test_configure_codex_preserves_arrays_of_tables(tmp_path):
    codex_path = tmp_path / "config.toml"
    codex_path.write_text(
        '[[profiles]]\nname = "work"\nmodel = "gpt"\n\n[[profiles]]\nname = "home"\n', encoding="utf-8"
    )
    configure_codex(codex_path)
    actual = {
        "profiles": _read_toml(codex_path)["profiles"],
        "server_present": "callback" in _read_toml(codex_path)["mcp_servers"],
    }
    expected = {"profiles": [{"name": "work", "model": "gpt"}, {"name": "home"}], "server_present": True}
    assert actual == expected


def test_configure_codex_warns_when_comments_will_be_dropped(tmp_path, capsys):
    codex_path = tmp_path / "config.toml"
    codex_path.write_text("# my notes\nmodel = \"gpt\"\n", encoding="utf-8")
    configure_codex(codex_path)
    err = capsys.readouterr().err
    actual = {"warned": "comments" in err and str(codex_path) in err, "comment_kept": "# my notes" in codex_path.read_text()}
    expected = {"warned": True, "comment_kept": False}
    assert actual == expected
```

(If `configure_codex` is not importable by that name in the test module, use whatever the neighbouring tests call.)

- [ ] **Step 2: Run them to verify they fail**

Run: `uv run pytest tests/test_cli.py -k "arrays_of_tables or comments_will_be_dropped" -q`
Expected: FAIL (`ConfigError: cannot serialize TOML value of type dict`; no warning).

- [ ] **Step 3: Implement**

In `callback/cli.py`:

```python
def _is_table_array(value: object) -> bool:
    return isinstance(value, list) and bool(value) and all(isinstance(item, Mapping) for item in value)


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
            for item in value:
                table_lines.append(f"[[{table_name}]]")
                table_lines.extend(_toml_lines(item, (*prefix, key)))
                table_lines.append("")
        else:
            scalar_lines.append(f"{_toml_key(key)} = {_toml_value(value)}")

    if scalar_lines and table_lines:
        return [*scalar_lines, "", *table_lines]
    return [*scalar_lines, *table_lines]
```

`_read_toml_config`: read the text once; if any line's `lstrip()` starts with `#`, `typer.echo(f"warning: {path} contains comments; callback rewrites this file and comments are not preserved", err=True)` before parsing. (Inline `# …` after a value is also a comment TOML allows; checking only full-line comments is the accepted ceiling — say so in a `# ponytail:` comment.)

- [ ] **Step 4: Verify**

Run: `uv run ruff check . && uv run ruff format --check . && uv run pyright && uv run pytest -m "not integration and not local" -q`
Expected: green.

- [ ] **Step 5: Commit**

```bash
git add -A
git commit -m "fix(cli): codex config writer keeps arrays of tables and warns before dropping comments (D8)"
```

---

### Task 8: Docs and INTENT bookkeeping

**Files:**
- Modify: `CLAUDE.md`, `AGENTS.md`, `README.md`, `skills/onboard-profile/SKILL.md`, `skills/tailor-resume/SKILL.md`, `INTENT.md`

- [ ] **Step 1: Env vars and module map**

`CLAUDE.md` "Env Vars": add `- XDG_DATA_HOME: Moves the whole data root (resumes, wiki, checkpoint DBs, compiled profile, applications archive) from ~/.local/share/callback to $XDG_DATA_HOME/callback.` Keep `CALLBACK_APPS_DIR` and note it overrides only the archive. In the module map add `| paths.py | Every data directory and the atomic writers |` and change the `profile_nodes.py` / any row that names `ProfileCompiler` or `WikiRenderer` to the function names. Update the "Checkpointer DB" lines to say the default and that `XDG_DATA_HOME` moves them.

`AGENTS.md`: same env-var wording at line 79 ("Overrides resume, wiki, and profile data roots" → every data root, list them) and the module map at line 240.

`README.md`: if it lists runtime dependencies or mentions `resume_label` on `load_jd`, update.

`skills/onboard-profile/SKILL.md` line ~130 and `skills/tailor-resume/SKILL.md` line ~21: delete the "pass `resume_label` when multiple resumes are registered" guidance; `load_jd` no longer takes it (one resume is registered at a time; `onboard_user` replaces it).

- [ ] **Step 2: INTENT bookkeeping**

In `INTENT.md`: rows D5, D8 → severity column `Fixed (M4)`; rows W3, W5, W6, W7, W8, W9, W10 → estimate column `Fixed (M4)`. In W11 append: `PLR09 was never enabled; M4 deleted the block. Enabling it today: 26 violations (13 PLR0913, 8 PLR0915, 3 PLR0911, 2 PLR0912), 10 in server.py — input for M5.` Under "M4 — Shed weight" replace "Done when" with the measured facts: `Done (M4): pyproject.toml lists 11 runtime dependencies (was 17); callback/paths.py owns every data directory and XDG_DATA_HOME moves all of them; the pylint block is gone (26 PLR09 violations recorded under W11).`

- [ ] **Step 3: Verify**

Run: `uv run pytest -m "not integration and not local" -q && grep -rn "resume_label" skills README.md CLAUDE.md AGENTS.md`
Expected: green; remaining `resume_label` hits refer to profile state / trace metadata only, not to a `load_jd` argument.

- [ ] **Step 4: Commit**

```bash
git add -A
git commit -m "docs: paths.py, XDG_DATA_HOME everywhere, 11 deps; INTENT M4 bookkeeping"
```

---

## Self-review notes

- **Spec coverage:** D5 → Task 1; D8 → Task 7; W3 → Task 2; W5 → Task 6; W6 → Task 1; W7 → Task 3; W8 → Task 5; W9 → Task 6; W10 → Task 6. "≤ 11 runtime deps" → Tasks 2–4 plus the ceiling test in Task 4. "one paths.py" → Task 1. "PLR09 passes or block removed" → Task 6 (removed) with the count recorded in Task 8.
- **INTENT is stale in two places** and the plan follows the code, not the table: `main.py` (W9) no longer exists; the "4 copies of `data_dir()`" are now 1 in `profilecompiler.py` plus 3 in `callback/repository/` (still four, in different files than the row implies).
- **Type consistency:** `paths.wiki_dir` is patched with `lambda: X` everywhere (zero-arg); `resolve_targets` returns `list[str]` and `install` consumes `list[str]`; `compile_profile` the node vs `compile_profile` the function is disambiguated by importing the function as `build_profile` in `profile_nodes.py`.
- **Task ordering is load-bearing:** Task 1 must land before Task 5 (its wikirenderer tests patch `callback.paths.wiki_dir`) and before Task 7 (which edits `cli.py` after Task 1 and Task 4 have already changed it). Do not reorder.
