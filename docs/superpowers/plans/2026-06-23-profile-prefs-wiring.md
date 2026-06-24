# Profile Preferences Wiring + Skill De-PII — Implementation Plan (Track A)

> **For agentic workers:** REQUIRED SUB-SKILL: superpowers:subagent-driven-development. Steps use checkbox (`- [ ]`) syntax.

**Goal:** Move all personalized logic into profile preferences + a per-project `.callback/config.json`, add an `init` skill, de-PII the job-search skills, and drop the bespoke automation skill.

**Architecture:** One Python change (extend `SearchPreferences`); the rest is skill/markdown authoring. Spec: `docs/superpowers/specs/2026-06-23-profile-prefs-wiring-design.md`.

**Tech Stack:** Python 3.12, Pydantic v2, pytest; Claude Code plugin skills (markdown).

## Global Constraints

- Pydantic v2 (`Field(default_factory=...)`, `model_validate`, `model_dump`).
- Skills must hardcode **no** personal values/paths — read prefs via `get_search_preferences`, paths from `.callback/config.json`, ledger via the `job-search-ledger` command.
- Honest-signal (north star): no fabrication, no keyword-stuffing, surface real gaps, don't oversell the score.
- `ruff check` + `ruff format` + `pyright` clean; full `uv run pytest` green; commit per task.
- Keep SBI (no STAR).

---

### Task A1: Extend `SearchPreferences`

**Files:**
- Modify: `callback/preferences.py`
- Test: `tests/test_preferences.py`

**Interfaces produced:**
- `ReferralCompany(name: str, note: str | None = None)`
- `SearchPreferences` gains: `referral_companies: list[ReferralCompany] = []`, `scan_sources: list[str] = []`, `lead_recency_days: int = 3`, `input_paths: list[str] = []`.

- [ ] **Step 1: Write failing tests** (append to `tests/test_preferences.py`):

```python
def test_new_fields_default_empty():
    prefs = SearchPreferences(**_valid_kwargs())
    dumped = prefs.model_dump()
    assert dumped["referral_companies"] == []
    assert dumped["scan_sources"] == []
    assert dumped["lead_recency_days"] == 3
    assert dumped["input_paths"] == []


def test_referral_company_nested_serialization():
    from callback.preferences import ReferralCompany

    prefs = SearchPreferences(
        **_valid_kwargs(
            referral_companies=[{"name": "Acme", "note": "ask Sam"}, {"name": "Globex"}],
            scan_sources=["gmail", "company_careers"],
            lead_recency_days=7,
            input_paths=["~/resumes", "~/Documents/jobs"],
        )
    )
    dumped = prefs.model_dump()
    assert dumped["referral_companies"] == [
        {"name": "Acme", "note": "ask Sam"},
        {"name": "Globex", "note": None},
    ]
    assert dumped["scan_sources"] == ["gmail", "company_careers"]
    assert dumped["lead_recency_days"] == 7
    assert dumped["input_paths"] == ["~/resumes", "~/Documents/jobs"]
```

(`_valid_kwargs` already exists in the file from the #53 tests; it supplies `home_location`, `work_types`, `updated_at`.)

- [ ] **Step 2: Run, verify fail**

Run: `uv run pytest tests/test_preferences.py -k "new_fields or referral_company_nested" -v`
Expected: FAIL (fields/`ReferralCompany` don't exist yet).

- [ ] **Step 3: Implement** in `callback/preferences.py`:

Add the model (next to `CompanyPref`):
```python
class ReferralCompany(BaseModel):
    name: str
    note: str | None = None
```
Add fields to `SearchPreferences` (after `comp_annual_target`, before `updated_at`):
```python
    # Group 5 — discovery + referral (skills read these; nothing hardcoded)
    referral_companies: list[ReferralCompany] = Field(default_factory=list)
    scan_sources: list[str] = Field(default_factory=list)
    lead_recency_days: int = 3
    input_paths: list[str] = Field(default_factory=list)
```

- [ ] **Step 4: Run, verify pass**

Run: `uv run pytest tests/test_preferences.py -v` → all pass.

- [ ] **Step 5: Full suite + lint + commit**

```bash
uv run pytest
uv run ruff format callback/preferences.py tests/test_preferences.py
uv run ruff check callback/preferences.py tests/test_preferences.py
uv run pyright callback/preferences.py
git add callback/preferences.py tests/test_preferences.py
git commit -m "feat: extend SearchPreferences with referral, scan sources, input paths"
```

**Note:** `set/get_search_preferences` validate the whole object, so the new fields flow through the existing tools with no server change. (Confirm `tests/test_server.py::TestSearchPreferencesTools` still passes in the full run.)

---

### Task A2: `init` skill

**Files:**
- Create: `skills/init/SKILL.md`
- Modify: nothing else (host-managed; no Python).

**This is a skill (markdown), not code — no unit tests.** Author it to Claude Code skill best practices (third-person description, focused body, progressive disclosure).

- [ ] **Step 1: Write `skills/init/SKILL.md`** with:
  - **Frontmatter:** `name: init`; third-person `description` covering triggers like "set up callback in this project", "start a job hunt here", "initialize callback", "bootstrap my job search". No `version:` key.
  - **North Star** one-liner (callback's: get past the ATS gate honestly).
  - **Flow:**
    1. **Scaffold project** — write `.callback/config.json` in the project root (prompt for paths or accept the defaults below) and create `data/`, `applications/`, `archive/`. Document the schema:
       ```json
       {
         "applications_dir": "./applications",
         "record_csv": "./data/record.csv",
         "ledger_db": "./data/ledger.sqlite3",
         "edd_xlsx": "./data/tracker.xlsx",
         "archive_dir": "./archive"
       }
       ```
    2. **Onboard** — ask for the resume path and `input_paths` (a list of source-file locations); call `onboard_user(...)` → `compile_profile()`. Follow the onboard-profile rules (truthful evidence only; never fabricate).
    3. **Capture preferences** — ask the preference questions (location, work types, comp target, target titles, seniority bands + blockers, target companies, core/skip domains, **referral_companies**, **scan_sources**, **lead_recency_days**) and call `set_search_preferences(...)`. Note: `set_search_preferences` fully replaces stored prefs.
    4. **Offer ledger install (optional)** — if the user wants EDD/unemployment tracking, point them to install the `job-search-ledger` tool (`uvx --from git+… job-search-ledger` or on PATH); don't hardcode a repo path. Skip if not wanted.
  - **Rules:** never fabricate; paths live in `.callback/config.json`; prefs live in the profile; re-running updates in place.

- [ ] **Step 2: Validate** — `claude plugin validate ./ --strict` passes (if `claude` available); `uv run pytest -q` stays green.

- [ ] **Step 3: Commit**
```bash
git add skills/init/SKILL.md
git commit -m "feat: add init skill — scaffold project config + onboarding + preferences"
```

---

### Task A3: De-PII skills, scan subagents, drop automation, polish

**Files:**
- Modify: `skills/scan-job-leads/SKILL.md`, `skills/review-job-application/SKILL.md`, `skills/auto-job-apply/SKILL.md` (+ its `references/record-schema.md`)
- Delete: `skills/setup-job-automation/SKILL.md`, `commands/setup-job-automation.md`
- Modify: `skills/onboard-profile/SKILL.md`, `skills/tailor-resume/SKILL.md` (polish only), `README.md`
- Also polish remaining `commands/*.md` if they restate personal values.

**Skill/markdown authoring — no unit tests.** Per-file changes:

- [ ] **Step 1: De-PII `scan-job-leads`, `review-job-application`, `auto-job-apply`**
  - Replace every hardcoded location/comp/domain/company/title/seniority value with "read via `get_search_preferences` and apply the user's configured values as the gates / advisory comp note."
  - Referral → "read `referral_companies`; surface referral leads for those companies."
  - Sources/recency → "scan the user's `scan_sources` within `lead_recency_days`."
  - Paths → "read from `.callback/config.json` (`applications_dir`, `record_csv`, `ledger_db`, `edd_xlsx`, `archive_dir`)"; ledger via the `job-search-ledger` command, not a path.
  - Remove all `~/...` absolute paths and stale `pi-apply` / `pi_apply_applications/` references.

- [ ] **Step 2: `scan-job-leads` subagents** — add explicit guidance: spawn one subagent per configured source (parallel), each returning only lead metadata (company/title/URL); do NOT load full email threads into the parent; parent merges + dedupes.

- [ ] **Step 3: Drop automation** — delete `skills/setup-job-automation/SKILL.md` and `commands/setup-job-automation.md`. Remove references to it from other skills (e.g. scan's "next action"). Add a README **"Scheduling a recurring scan"** section: point your scheduler at `scan-job-leads`, with one Claude `/schedule` example and one `cron` example.

- [ ] **Step 4: Polish + north-star caveats** (all remaining skills)
  - Rewrite `description`s in third person, broader trigger coverage.
  - Drop the `version:` frontmatter key everywhere it appears.
  - North-star #6: where skills cite "covered" skills, note covered = mentioned in a bullet, not necessarily demonstrated.
  - North-star #7: in `auto-job-apply`, the sub-70 referral path must still surface the real keyword/format gaps.

- [ ] **Step 5: Validate + commit**
```bash
claude plugin validate ./ --strict   # if available
uv run pytest -q                      # stays green
git add skills commands README.md
git commit -m "refactor: de-PII job-search skills to read prefs + project config; drop automation skill"
```

---

## Self-review checklist (run after writing the plan)

- A1 covers every new field (referral_companies, scan_sources, lead_recency_days, input_paths) ✓
- `.callback/config.json` schema appears once (A2) and is referenced (not redefined) by A3 ✓
- No skill retains a hardcoded personal value or absolute path after A3 ✓
- `setup-job-automation` skill + command both deleted; README scheduling note added ✓
