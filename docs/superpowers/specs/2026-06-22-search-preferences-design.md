# Search Preferences — Design

**Date:** 2026-06-22
**Status:** Approved (brainstorming) — pending spec review
**Author:** Dan Sedano (with Claude)

## Problem

The plugin's job-search skills (`scan-job-leads`, `review-job-application`,
`setup-job-automation`, `auto-job-apply`) hardcode personal search criteria:
home location (San Diego), comp target ($150k), target companies (FAANG),
core/skip domains, target titles, and seniority bands. This blocks the plugin
from being **public/portfolio-shippable** — every user would inherit Dan's
preferences, and the skills leak PII.

Search criteria are **per-user config**, not code. They belong in the user's
profile, captured at onboard, and read back as a slim slice when scanning.

## Goal

Add a standalone **search-preferences** subsystem to callback:
1. Capture search preferences at onboard (and let them be updated independently).
2. Persist them as config, decoupled from the compiled profile.
3. Expose a **slim read** so scan/review pull only preferences — never the full
   compiled profile, stories, or wiki.

## Non-Goals (YAGNI)

- **Multi-profile preferences.** One user, one `preferences.json`.
- **Enforcement logic inside callback.** callback stores and returns
  preferences; the host skills interpret them (gates, bias, advisory notes).
  callback stays dumb config I/O.
- **De-PII of the consuming skills** beyond wiring them to `get_search_preferences`.
  The full scan/review/auto skill rewrite (delegation, EDD-ledger extraction) is
  follow-on work that *depends on* this subsystem; it is not specified here.
- **Graph integration.** Preferences are a flat config artifact, not graph
  state — consistent with the walking-skeleton discipline (`BRIEF.md`).

## Decisions (locked in brainstorming)

| Decision | Choice |
|---|---|
| Audience | Public / portfolio |
| Read interface | New dedicated `get_search_preferences` MCP tool |
| Storage / lifecycle | **Approach A** — standalone `PreferencesStore`, captured at onboard, updatable without re-onboarding |
| Orchestrator pattern | `auto-job-apply` delegates to piecemeal skills (separate follow-on) |

## Schema

`SearchPreferences` (Pydantic, in `callback/preferences.py`). Four field groups,
each mapping to a real consumer behavior:

```python
class WorkType(str, Enum):
    onsite_local = "onsite_local"
    hybrid_local = "hybrid_local"
    remote = "remote"

class CompanyPref(BaseModel):
    name: str
    level_mapping: str | None = None   # optional, advisory note for the host

class SearchPreferences(BaseModel):
    schema_version: str = "1"
    # Group 1 — HARD GATE
    home_location: str                 # e.g. "San Diego, CA"
    work_types: list[WorkType]         # accepted work arrangements
    # Group 2 — bias + blockers
    target_titles: list[str]           # e.g. ["Software Engineer", "AI Engineer"]
    seniority_bands: list[str]         # acceptable bands, e.g. ["mid", "senior"]
    seniority_blockers: list[str]      # hard skips, e.g. ["staff", "principal"]
    target_companies: list[CompanyPref]
    # Group 3 — DOMAIN GATE
    core_domains: list[str]            # prefer
    skip_domains: list[str]            # skip before scoring
    # Group 4 — ADVISORY ONLY
    comp_currency: str = "USD"
    comp_annual_target: float | None = None
    updated_at: str
```

### Consumer contract (how the host honors each group)

| Group | Behavior in scan/review |
|---|---|
| `home_location` + `work_types` | **Hard gate.** Drop roles not local/remote-workable. |
| `target_titles` / `seniority_bands` | Bias / prioritize the queue. |
| `seniority_blockers` | Hard skip (e.g. staff/principal). |
| `target_companies` | Always-check list; `level_mapping` is an advisory note. |
| `core_domains` / `skip_domains` | **Domain gate.** Skip off-domain before scoring. |
| `comp_*` | **Advisory only.** Surface "below / at / above target" as a note. **Never gate, never reprioritize.** |

## Components

```
callback/preferences.py          SearchPreferences model + PreferencesStore (save/load)
callback/server.py               +set_search_preferences, +get_search_preferences tools
tests/test_preferences.py        store round-trip, missing-file, validation
tests/test_server.py             tool round-trip + get-when-missing next_action
```

`PreferencesStore` mirrors `AccomplishmentsStore`:

- Path: `~/.local/share/callback/preferences.json`
- `save(prefs: SearchPreferences) -> None` — atomic write.
- `load() -> SearchPreferences | None` — `None` when the file is absent.
- Injectable `base_dir` for tests (same pattern as `AccomplishmentsStore`).

## MCP Tools

Both return the standard `_ok` / `_err` envelope.

### `set_search_preferences(preferences: dict)`
- Validate `preferences` against `SearchPreferences` (Pydantic). **Fail fast** on
  invalid input → `_err` with a validation message (no silent coercion).
- Stamp `updated_at`, persist, return `_ok` with the stored prefs echoed back.

### `get_search_preferences()`
- Returns **only** the preferences object — never the compiled profile, stories,
  or wiki. This *is* the slim slice.
- When no preferences exist: `_ok` with `data: null` and
  `next_action: "set_search_preferences"` — an **explicit uninitialized state**,
  not a silent default. Skills use this to prompt the user.

## Data Flow

```
onboard-profile skill
  └─ onboard_user (resume) → compile_profile
  └─ asks user: location? work types? titles/seniority? companies?
                domains? comp target?
  └─ set_search_preferences(prefs)        ← capture

(any time, no re-onboard)
  └─ set_search_preferences(prefs)        ← update

scan-job-leads / review-job-application skills
  └─ get_search_preferences()             ← slim read (config only)
  └─ apply location gate, domain gate, bias, advisory comp note
```

## Error Handling & Observability

- Invalid `set` payload → `_err` (fail fast, explicit message). No partial writes.
- Missing prefs on `get` → explicit `next_action`, never a fabricated default.
- Both tools log structured stderr JSON consistent with existing tools
  (tool name, session id). Preferences values are user config, not sensitive
  resume/JD content, so they may appear in logs; **no API keys or secrets are in
  this schema.**

## Testing

- **Unit (`PreferencesStore`):** save→load round-trip returns an equal object;
  load on missing file returns `None`; injectable `base_dir` isolates tests.
- **Schema:** invalid input (missing required field, bad enum) raises validation.
- **Tools:** `set`→`get` round-trip returns the stored object; `get` with no
  prefs returns `next_action: set_search_preferences`.
- Assertions use full-object comparison (`assert actual == expected`), per repo
  convention.

## Milestones

- **M1 — Schema + store.** `SearchPreferences` + `PreferencesStore` + unit tests.
- **M2 — MCP tools.** `set_search_preferences` / `get_search_preferences` in
  `server.py` + tool tests. (Vertical slice: set/get works end-to-end.)
- **M3 — Capture.** `onboard-profile` skill asks the questions and calls `set`;
  an "update my job preferences" trigger reuses `set`.
- **M4 — Consume + de-PII.** `scan-job-leads` and `review-job-application` read
  via `get` and drop hardcoded location/comp/domains/companies. (This is the
  public-shippability payoff; larger skill rewrite tracked separately.)

## Open Questions

- None blocking. M4's full skill rewrite (delegation pattern, EDD-ledger
  extraction for public release) will get its own spec.
