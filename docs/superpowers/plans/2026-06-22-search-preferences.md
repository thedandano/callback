# Search Preferences Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add a standalone search-preferences subsystem to callback — a domain model, a persistence store, and two MCP tools — so job-search skills read per-user criteria as a slim slice instead of hardcoding them.

**Architecture:** Three focused units following existing codebase patterns: a pure Pydantic domain model (`callback/preferences.py`), a persistence store mirroring `AccomplishmentsStore` (`callback/repository/preferences.py`), and two MCP tools in `server.py` (`set_search_preferences`, `get_search_preferences`) returning the standard `_ok`/`_err` envelope. Preferences are flat config, not graph state.

**Tech Stack:** Python 3, Pydantic v2, FastMCP, pytest.

## Global Constraints

- Pydantic v2 models (`model_validate`, `model_dump`, `Field(default_factory=...)`).
- Envelopes via existing `_ok` / `_err` helpers in `server.py`. Never hand-roll envelopes.
- **Fail fast, no silent fallback:** invalid input → `_err`; missing prefs → explicit `next_action`, never a fabricated default.
- Atomic writes: temp file + `os.replace`, mirroring `AccomplishmentsStore._save`.
- Store path respects `XDG_DATA_HOME` (tests set it to `tmp_path`); `base_dir` injectable for unit tests.
- Tests use full-object comparison (`assert actual == expected`), not piecemeal key checks.
- `ruff check`, `ruff format`, and `pyright` must pass (CI enforces them).
- Each task ends with a commit.
- One responsibility per file. Domain model and persistence stay in separate files.

---

### Task 1: SearchPreferences domain model

**Files:**
- Create: `callback/preferences.py`
- Test: `tests/test_preferences.py`

**Interfaces:**
- Consumes: nothing.
- Produces: `WorkType` (str Enum: `onsite_local`, `hybrid_local`, `remote`), `CompanyPref(name: str, level_mapping: str | None = None)`, and `SearchPreferences` with fields:
  `schema_version: str = "1"`, `home_location: str` (required), `work_types: list[WorkType]` (required), `target_titles: list[str] = []`, `seniority_bands: list[str] = []`, `seniority_blockers: list[str] = []`, `target_companies: list[CompanyPref] = []`, `core_domains: list[str] = []`, `skip_domains: list[str] = []`, `comp_currency: str = "USD"`, `comp_annual_target: float | None = None`, `updated_at: str` (required).

- [ ] **Step 1: Write the failing tests**

```python
# tests/test_preferences.py
"""Unit tests for callback.preferences domain model."""

import pytest
from pydantic import ValidationError

from callback.preferences import CompanyPref, SearchPreferences, WorkType


def _valid_kwargs(**overrides) -> dict:
    defaults = dict(
        home_location="Anytown, USA",
        work_types=[WorkType.hybrid_local, WorkType.remote],
        updated_at="2026-06-22T00:00:00+00:00",
    )
    return {**defaults, **overrides}


def test_minimal_valid_preferences_apply_defaults():
    prefs = SearchPreferences(**_valid_kwargs())

    assert prefs.model_dump() == {
        "schema_version": "1",
        "home_location": "Anytown, USA",
        "work_types": ["hybrid_local", "remote"],
        "target_titles": [],
        "seniority_bands": [],
        "seniority_blockers": [],
        "target_companies": [],
        "core_domains": [],
        "skip_domains": [],
        "comp_currency": "USD",
        "comp_annual_target": None,
        "updated_at": "2026-06-22T00:00:00+00:00",
    }


def test_company_pref_nested_serialization():
    prefs = SearchPreferences(
        **_valid_kwargs(
            target_companies=[
                {"name": "Acme", "level_mapping": "L4 == mid"},
                {"name": "Stripe"},
            ]
        )
    )

    assert prefs.model_dump()["target_companies"] == [
        {"name": "Acme", "level_mapping": "L4 == mid"},
        {"name": "Stripe", "level_mapping": None},
    ]


def test_missing_home_location_rejected():
    kwargs = _valid_kwargs()
    del kwargs["home_location"]
    with pytest.raises(ValidationError):
        SearchPreferences(**kwargs)


def test_invalid_work_type_rejected():
    with pytest.raises(ValidationError):
        SearchPreferences(**_valid_kwargs(work_types=["from_mars"]))


def test_company_pref_defaults_level_mapping_none():
    assert CompanyPref(name="Acme").model_dump() == {"name": "Acme", "level_mapping": None}
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `uv run pytest tests/test_preferences.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'callback.preferences'`

- [ ] **Step 3: Write the model**

```python
# callback/preferences.py
"""Search-preferences domain model.

Per-user job-search criteria captured at onboard and read as a slim slice by the
scan/review skills. Pure schema — no I/O. Persistence lives in
callback.repository.preferences.
"""

from enum import Enum

from pydantic import BaseModel, Field


class WorkType(str, Enum):
    onsite_local = "onsite_local"
    hybrid_local = "hybrid_local"
    remote = "remote"


class CompanyPref(BaseModel):
    name: str
    level_mapping: str | None = None


class SearchPreferences(BaseModel):
    schema_version: str = "1"
    # Group 1 — hard gate
    home_location: str
    work_types: list[WorkType]
    # Group 2 — bias + blockers
    target_titles: list[str] = Field(default_factory=list)
    seniority_bands: list[str] = Field(default_factory=list)
    seniority_blockers: list[str] = Field(default_factory=list)
    target_companies: list[CompanyPref] = Field(default_factory=list)
    # Group 3 — domain gate
    core_domains: list[str] = Field(default_factory=list)
    skip_domains: list[str] = Field(default_factory=list)
    # Group 4 — advisory only
    comp_currency: str = "USD"
    comp_annual_target: float | None = None
    updated_at: str
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `uv run pytest tests/test_preferences.py -v`
Expected: PASS (5 tests)

- [ ] **Step 5: Lint, type-check, commit**

```bash
uv run ruff format callback/preferences.py tests/test_preferences.py
uv run ruff check callback/preferences.py tests/test_preferences.py
uv run pyright callback/preferences.py
git add callback/preferences.py tests/test_preferences.py
git commit -m "feat: SearchPreferences domain model"
```

---

### Task 2: PreferencesStore persistence

**Files:**
- Create: `callback/repository/preferences.py`
- Test: `tests/test_repository_preferences.py`

**Interfaces:**
- Consumes: `SearchPreferences` from `callback.preferences`.
- Produces: `data_dir() -> Path` (honors `XDG_DATA_HOME`, else `~/.local/share/callback`); `PreferencesStore(base_dir: Path | None = None)` with `save(prefs: SearchPreferences) -> None` (atomic write to `<base_dir>/preferences.json`) and `load() -> SearchPreferences | None` (`None` when the file is absent).

- [ ] **Step 1: Write the failing tests**

```python
# tests/test_repository_preferences.py
"""Unit tests for callback.repository.preferences."""

import json

from callback.preferences import SearchPreferences, WorkType
from callback.repository.preferences import PreferencesStore


def _make_prefs(**overrides) -> SearchPreferences:
    defaults = dict(
        home_location="Anytown, USA",
        work_types=[WorkType.remote],
        target_titles=["Software Engineer"],
        updated_at="2026-06-22T00:00:00+00:00",
    )
    return SearchPreferences(**{**defaults, **overrides})


def test_save_then_load_round_trip(tmp_path):
    store = PreferencesStore(base_dir=tmp_path)
    prefs = _make_prefs()

    store.save(prefs)
    loaded = store.load()

    assert loaded == prefs


def test_load_missing_returns_none(tmp_path):
    store = PreferencesStore(base_dir=tmp_path)

    assert store.load() is None


def test_save_overwrites_in_place(tmp_path):
    store = PreferencesStore(base_dir=tmp_path)
    store.save(_make_prefs(home_location="Anytown, USA"))
    store.save(_make_prefs(home_location="Remote, US"))

    loaded = store.load()

    assert loaded == _make_prefs(home_location="Remote, US")


def test_file_is_valid_json_after_save(tmp_path):
    store = PreferencesStore(base_dir=tmp_path)
    store.save(_make_prefs())

    with open(tmp_path / "preferences.json") as f:
        data = json.load(f)

    assert data["schema_version"] == "1"
    assert data["home_location"] == "Anytown, USA"
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `uv run pytest tests/test_repository_preferences.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'callback.repository.preferences'`

- [ ] **Step 3: Write the store**

```python
# callback/repository/preferences.py
import json
import os
from pathlib import Path

from callback.preferences import SearchPreferences


def data_dir() -> Path:
    if xdg_data_home := os.environ.get("XDG_DATA_HOME"):
        return Path(xdg_data_home) / "callback"
    return Path.home() / ".local" / "share" / "callback"


class PreferencesStore:
    def __init__(self, base_dir: Path | None = None):
        self._base_dir = base_dir if base_dir is not None else data_dir()

    def _file_path(self) -> Path:
        return self._base_dir / "preferences.json"

    def load(self) -> SearchPreferences | None:
        file_path = self._file_path()
        if not file_path.exists():
            return None
        with open(file_path) as f:
            return SearchPreferences.model_validate(json.load(f))

    def save(self, prefs: SearchPreferences) -> None:
        file_path = self._file_path()
        file_path.parent.mkdir(parents=True, exist_ok=True)
        tmp_path = file_path.with_suffix(".json.tmp")
        with open(tmp_path, "w") as f:
            json.dump(prefs.model_dump(), f)
        os.replace(tmp_path, file_path)
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `uv run pytest tests/test_repository_preferences.py -v`
Expected: PASS (4 tests)

- [ ] **Step 5: Lint, type-check, commit**

```bash
uv run ruff format callback/repository/preferences.py tests/test_repository_preferences.py
uv run ruff check callback/repository/preferences.py tests/test_repository_preferences.py
uv run pyright callback/repository/preferences.py
git add callback/repository/preferences.py tests/test_repository_preferences.py
git commit -m "feat: PreferencesStore persistence for search preferences"
```

---

### Task 3: set/get MCP tools

**Files:**
- Modify: `callback/server.py` (imports near top with the other `callback.*` imports; add two tools after the `create_story` tool, ~line 1331)
- Test: `tests/test_server.py` (append a new test class)

**Interfaces:**
- Consumes: `SearchPreferences` from `callback.preferences`; `PreferencesStore` from `callback.repository.preferences`; existing `_ok`, `_err`, `_log`; `uuid`, `datetime`, `ValidationError`.
- Produces MCP tools:
  - `set_search_preferences(preferences: dict) -> str` — stamps `updated_at` server-side, validates, persists; `_ok` echoes `{"preferences": <dumped>}`; invalid input → `_err(code="invalid_preferences", retriable=True)`.
  - `get_search_preferences() -> str` — `_ok` with `data={"preferences": <dumped>}`, or `_ok(next_action="set_search_preferences", data=None)` when none stored.

- [ ] **Step 1: Add imports**

In `callback/server.py`, add `from pydantic import ValidationError` with the third-party imports, and these with the existing `from callback.*` imports:

```python
from callback.preferences import SearchPreferences
from callback.repository.preferences import PreferencesStore
```

(`uuid` and `datetime` are already imported.)

- [ ] **Step 2: Write the failing tests**

`tests/test_server.py` imports the server **inside** test bodies (existing
convention — see `from callback.server import load_jd` at ~line 172), which keeps
imports out of module scope and avoids ruff E402. `json` and `pytest` are already
imported at the top. Append this test class at the end of the file:

```python
# tests/test_server.py  — append
class TestSearchPreferencesTools:
    @pytest.fixture(autouse=True)
    def _isolate(self, tmp_path, monkeypatch):
        monkeypatch.setenv("XDG_DATA_HOME", str(tmp_path))

    def _valid_payload(self) -> dict:
        return {
            "home_location": "Anytown, USA",
            "work_types": ["hybrid_local", "remote"],
            "target_titles": ["Software Engineer", "AI Engineer"],
        }

    def test_set_then_get_round_trip(self):
        from callback.server import get_search_preferences, set_search_preferences

        set_env = json.loads(set_search_preferences(self._valid_payload()))
        assert set_env["status"] == "ok"
        stored = set_env["data"]["preferences"]

        get_env = json.loads(get_search_preferences())
        assert get_env["status"] == "ok"
        assert get_env["data"]["preferences"] == stored

    def test_set_stamps_updated_at(self):
        from callback.server import set_search_preferences

        set_env = json.loads(set_search_preferences(self._valid_payload()))
        assert set_env["data"]["preferences"]["updated_at"]  # non-empty ISO string

    def test_get_when_missing_returns_next_action(self):
        from callback.server import get_search_preferences

        get_env = json.loads(get_search_preferences())
        assert get_env["status"] == "ok"
        assert get_env["next_action"] == "set_search_preferences"
        assert "data" not in get_env

    def test_set_invalid_payload_returns_error(self):
        from callback.server import set_search_preferences

        env = json.loads(set_search_preferences({"work_types": ["remote"]}))  # no home_location
        assert env["status"] == "error"
        assert env["error"]["code"] == "invalid_preferences"
        assert env["error"]["stage"] == "set_search_preferences"
```

- [ ] **Step 3: Run tests to verify they fail**

Run: `uv run pytest tests/test_server.py::TestSearchPreferencesTools -v`
Expected: FAIL with `ImportError: cannot import name 'set_search_preferences'`

- [ ] **Step 4: Write the tools**

Add after the `create_story` tool in `callback/server.py`:

```python
@mcp.tool()
def set_search_preferences(preferences: dict) -> str:
    """Persist the user's job-search preferences.

    Args:
        preferences: SearchPreferences fields. home_location and work_types are
            required; updated_at is stamped server-side.

    Returns:
        JSON envelope echoing the stored preferences under data.preferences.
    """
    session_id = str(uuid.uuid4())
    _log("INFO", {"tool": "set_search_preferences", "session_id": session_id})

    stamped = {**preferences, "updated_at": datetime.datetime.now(datetime.UTC).isoformat()}
    try:
        prefs = SearchPreferences.model_validate(stamped)
    except ValidationError as exc:
        return _err(
            stage="set_search_preferences",
            code="invalid_preferences",
            message=str(exc),
            session_id=session_id,
            retriable=True,
        )

    PreferencesStore().save(prefs)
    return _ok(session_id, None, {"preferences": prefs.model_dump()})


@mcp.tool()
def get_search_preferences() -> str:
    """Return the user's job-search preferences (slim slice; no profile data).

    Returns:
        JSON envelope with data.preferences, or next_action=set_search_preferences
        when none are stored.
    """
    session_id = str(uuid.uuid4())
    _log("INFO", {"tool": "get_search_preferences", "session_id": session_id})

    prefs = PreferencesStore().load()
    if prefs is None:
        return _ok(session_id, "set_search_preferences", None)
    return _ok(session_id, None, {"preferences": prefs.model_dump()})
```

- [ ] **Step 5: Run tests to verify they pass**

Run: `uv run pytest tests/test_server.py::TestSearchPreferencesTools -v`
Expected: PASS (4 tests)

- [ ] **Step 6: Full suite, lint, type-check, commit**

```bash
uv run pytest
uv run ruff format callback/server.py tests/test_server.py
uv run ruff check callback/server.py tests/test_server.py
uv run pyright callback/server.py
git add callback/server.py tests/test_server.py
git commit -m "feat: set/get_search_preferences MCP tools"
```

---

## Follow-on (out of scope for this plan)

- **M3 — Capture.** Wire the `onboard-profile` skill (markdown) to ask the preference questions and call `set_search_preferences`; add an "update my job preferences" trigger. Skill-file edits, no unit tests.
- **M4 — Consume + de-PII.** Rewire `scan-job-leads` / `review-job-application` to read via `get_search_preferences` and drop hardcoded location/comp/domains/companies. Tracked in its own spec (larger skill rewrite + delegation pattern).
