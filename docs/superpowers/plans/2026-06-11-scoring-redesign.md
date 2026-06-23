# Scoring Redesign (v2) Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Make callback's ATS score honest and standalone — wire ExperienceFit to real candidate data, reweight to 55/15/10/10/10, add knockout warnings, kill go-apply parity framing, and fix the scorer bugs found by the 2026-06-11 council reviews.

**Architecture:** The scorer (`callback/scorer.py`) stays a pure deterministic function. Candidate years are computed once in the `parse_initial` graph node (from the source resume's `SectionMap`), stored on `ApplyState`, and fed to both score runs so the delta stays clean. ExperienceFit becomes years-only (candidate seniority has no data source yet — deferred); when years can't be evaluated, the dimension is `None` and the composite renormalizes to /100. Knockout warnings surface in the report node, modeling the binary screener-question reality.

**Tech Stack:** Python 3.12, dataclasses, Pydantic v2 (graph state), pytest, pyright, uv.

---

## Context primer (read before starting)

- Repo: `/Users/dandano/workplace/callback`. Run everything via `uv run ...` from the repo root.
- All tests: `uv run pytest -q` (490 pass at baseline, ~30s). Type-check: `uv run pyright`.
- If pytest errors about a missing interpreter, the venv is stale: `rm -rf .venv && uv sync`.
- Test convention (non-negotiable, per project memory): **full-object equality** — `assert actual == expected` with complete dicts, never piecemeal key checks. Look at `tests/test_scoring_engine.py::TestRunScore` for the house style.
- Workflow: **single feature branch `feat/scoring-redesign-v2` → one PR to `main` at the very end** (user override 2026-06-11; supersedes the PR-per-milestone default). Conventional commits per task.
- Decision context: go-apply (the Go predecessor) is **deprecated** as of 2026-06-11. It is not a parity target. Its binary is wired into nothing at runtime (`bridge.py` is dead code kept for its tests — do not delete it in this plan).
- Locked design decisions (do not relitigate):
  - **One composite score** 0–100, weights KeywordMatch 55 / ExperienceFit 15 / ImpactEvidence 10 / ATSFormat 10 / Readability 10, pass threshold 70.
  - ExperienceFit is **years-only** in v2. Candidate seniority has no data source; the `exact|one_off|two_or_more_off` enum and seniority multipliers get **deleted**.
  - When ExperienceFit can't be evaluated (JD states no years, or resume dates unparseable), `experience_fit = None` and `total = (sum of other dims) × full_max/(full_max − exp_weight)` — i.e. ×100/85 with default weights. Never display a constant as a measurement.
  - Knockout warnings: any years shortfall → "LIKELY KNOCKOUT"; required ≥ 2× candidate → "STRONG KNOCKOUT RISK". Overqualification keeps the existing 0.85 multiplier (no warning).
  - Keyword matcher gains **only**: slash-spacing normalization ("CI/CD" ↔ "CI / CD") and conservative trailing-s plural tolerance (alpha final token, stem ≥ 4 chars). **No** synonym maps, **no** abbreviation expansion (k8s ≠ Kubernetes).
  - `SCORING_ENGINE_VERSION = "v2"` from M2 onward. All milestones land in one PR, so v2 is tagged consistently.

**Out of scope (do not do):** candidate-seniority data source (separate future proposal), `docs/architecture.html` redraw, removing `bridge.py`, the 401k impact-metric false positive, CI hash-seed matrix, the `wiki-ingest` cleanup items (envelope rework, graph singleton).

---

## Milestone 0 — go-apply deprecation doc sweep

Pure documentation; no behavior change. One commit per task is fine, or one commit for the whole milestone.

### Task 0.1: Fix CLAUDE.md factual errors

**Files:**
- Modify: `CLAUDE.md`

- [ ] **Step 1: Remove the false go-apply binary requirement**

In the Commands section, replace:

```
# Run the MCP server (stdio). go-apply binary must be on PATH or set GO_APPLY_BIN.
GO_APPLY_BIN=/path/to/go-apply uv run python -m callback.server
```

with:

```
# Run the MCP server (stdio)
uv run python -m callback.server
```

(Verified: nothing in the package imports `bridge.py`; the server runs without the binary.)

- [ ] **Step 2: Fix the apply-graph interrupt description**

Replace:

```
Linear graph with host handoff interrupts after `jd_fetch` and `keywords_accept`:
```

with:

```
Linear graph with host handoff interrupts after `jd_fetch` and before `tailor`:
```

(Source of truth: `callback/apply_graph.py:137-138` — `interrupt_after=[JD_FETCH_NODE]`, `interrupt_before=[TAILOR_NODE]`.)

- [ ] **Step 3: Fix the `onboard_user` tool-table row**

Replace:

```
| `onboard_user`   | profile  | Currently calls `profile_nodes.onboard` directly (skeleton).|
```

with:

```
| `onboard_user`   | profile  | Enters the profile graph (interrupts after `onboard`).      |
```

(Source of truth: `callback/server.py` builds and invokes the profile graph for `onboard_user`; CLAUDE.md's own Note below the profile diagram already says so.)

- [ ] **Step 4: Fix the profile-graph interrupt list**

Replace:

```
Cyclic, with interrupts after `onboard` and `create_story`:
```

with:

```
Cyclic, with interrupts after `onboard`, `compile_profile`, and `create_story`:
```

(Source of truth: `callback/profile_graph.py:112`.)

- [ ] **Step 5: Make the weights rule honest about where config lives**

In Change Discipline, replace:

```
- Scoring weights live in config — don't hardcode them.
```

with:

```
- Scoring weights and thresholds live in `ScoringConfig` (`scorer.py`) — change them there; never scatter new hardcoded weights.
```

- [ ] **Step 6: Correct the bridge.py framing**

Replace:

```
go-apply is deprecated; this binary is a legacy runtime dependency, not a design reference.
```

with:

```
go-apply is deprecated and its binary is wired into nothing at runtime — `bridge.py` is a dead legacy adapter kept only for its tests, not a design reference.
```

- [ ] **Step 7: Add the "what this score cannot see" paragraph**

In the Scoring section, directly after the "Rubric grounding" paragraph, add:

```
**What this score cannot see:** work-authorization and location knockouts (the
most common auto-dispositions), title match against the req, skill recency, and
degree/clearance filters. The score is a predictor of search retrievability and
skim survival, not a guarantee — do not oversell the number in report copy.
```

- [ ] **Step 8: Verify and commit**

Run: `grep -n "go-apply binary must be on PATH\|after \`jd_fetch\` and \`keywords_accept\`" CLAUDE.md`
Expected: no matches.

```bash
git add CLAUDE.md
git commit -m "docs: fix CLAUDE.md factual errors found in council review"
```

### Task 0.2: Mirror the deprecation into AGENTS.md

**Files:**
- Modify: `AGENTS.md` (stale lines: 17, 69, 209, 222–223, 244, 252)

- [ ] **Step 1: Apply the six edits**

1. Line 17 — replace:
   ```
   callback is a LangGraph MCP server (stdio only) that replaces the Go FSM in go-apply.
   ```
   with:
   ```
   callback is a standalone LangGraph MCP server (stdio only). It originated as a replacement for go-apply's Go FSM; go-apply is now deprecated and is not a parity target — callback's own behavior is the source of truth.
   ```
2. Line 69 — replace:
   ```
   - `GO_APPLY_BIN`: Path to the go-apply binary used by `bridge.py`.
   ```
   with:
   ```
   - `GO_APPLY_BIN`: Legacy; read only by `bridge.py`, which is wired into nothing at runtime.
   ```
3. Line 209 — replace:
   ```
   Pure deterministic Python - no I/O, no LLM calls. Ported from go-apply's `scorer.go`.
   ```
   with:
   ```
   Pure deterministic Python - no I/O, no LLM calls.
   ```
4. Lines 222–223 — replace:
   ```
   `bridge.py` still resolves the go-apply binary at import time and exposes subprocess helpers for the legacy Go CLI.
   If the binary is not on `PATH`, set `GO_APPLY_BIN=/path/to/go-apply` before importing.
   ```
   with:
   ```
   go-apply is deprecated and its binary is wired into nothing at runtime — `bridge.py` is a dead legacy adapter kept only for its tests, not a design reference.
   It resolves the binary at import time; tests point it at a fake binary (see `tests/conftest.py`).
   ```
5. Line 244 — replace:
   ```
   | `bridge.py` | go-apply subprocess wrapper |
   ```
   with:
   ```
   | `bridge.py` | dead legacy go-apply adapter (kept for tests only) |
   ```
6. Line 252 — replace:
   ```
   - Don't add scoring heuristics not present in go-apply unless explicitly requested.
   ```
   with:
   ```
   - New scoring heuristics must map to a real ATS gate mechanism and stay deterministic — go-apply parity is no longer a constraint.
   ```

- [ ] **Step 2: Verify and commit**

Run: `grep -cn "go-apply" AGENTS.md`
Expected: only the deprecation-note lines added above remain (read each remaining match; none may frame go-apply as normative).

```bash
git add AGENTS.md
git commit -m "docs: mirror go-apply deprecation into AGENTS.md"
```

### Task 0.3: Replace the scorer.py parity docstring

**Files:**
- Modify: `callback/scorer.py:1-5`

- [ ] **Step 1: Replace the module docstring**

Replace:

```python
"""ATS scoring engine — pure function, no I/O, no LLM calls.

Ported from go-apply internal/service/scorer/scorer.go.
Weights and thresholds match internal/config/defaults.json exactly.
"""
```

with:

```python
"""ATS scoring engine — pure function, no I/O, no LLM calls.

Each dimension proxies a real ATS gate mechanism: recruiter keyword search
(KeywordMatch), years knockout filters (ExperienceFit), parse failures
(ATSFormat), and the recruiter skim (ImpactEvidence, Readability).
Deterministic: identical inputs always produce identical outputs.
Weights and thresholds live in ScoringConfig below — callback-owned, not
inherited from any external system.
"""
```

- [ ] **Step 2: Run tests and commit**

Run: `uv run pytest -q`
Expected: 490 passed.

```bash
git add callback/scorer.py
git commit -m "docs: replace go-apply parity docstring with rubric grounding"
```

### Task 0.4: Sweep remaining stale references

**Files:**
- Modify: `.env.example`, `BRIEF.md:13`, `openspec/specs/jd-keyword-contract/spec.md:27-28`, `openspec/specs/accomplishments-repository/spec.md:12`, `pyproject.toml:4`, `README.md:166-167`

- [ ] **Step 1: .env.example — drop the GO_APPLY_BIN block**

Delete these lines:

```
# Path to the go-apply binary. Falls back to go-apply on PATH if unset.
GO_APPLY_BIN=

```

- [ ] **Step 2: BRIEF.md line 13 — drop the dead clause**

Replace:

```
`bridge.py` remains only as a legacy subprocess adapter where still needed.
```

with:

```
`bridge.py` remains only as a dead legacy adapter (wired into nothing at runtime; kept for its tests).
```

- [ ] **Step 3: openspec — make the JDData contract callback-owned**

In `openspec/specs/jd-keyword-contract/spec.md`, replace:

```
### Requirement: JDData contract matches go-apply
The system SHALL accept host-provided JDData using the same JSON-compatible contract as `go-apply`: `title`, `company`, `required`, `preferred`, `location`, `seniority`, `required_years`, `team`, `key_responsibilities`, `pay_range_min`, and `pay_range_max`.
```

with:

```
### Requirement: JDData contract
The system SHALL accept host-provided JDData using this JSON-compatible contract: `title`, `company`, `required`, `preferred`, `location`, `seniority`, `required_years`, `team`, `key_responsibilities`, `pay_range_min`, and `pay_range_max`.
```

In `openspec/specs/accomplishments-repository/spec.md` line 12, replace ` (go-apply compatible)` with `` (delete the parenthetical).

- [ ] **Step 4: pyproject.toml — real description**

Replace:

```toml
description = "Add your description here"
```

with:

```toml
description = "ATS-honest resume tailoring: a LangGraph MCP server that scores, tailors, and renders job applications"
```

- [ ] **Step 5: README.md — fix the --purge attribution**

Replace:

```
`--purge` deletes `~/.local/share/callback/` (application PDFs and JSON archives) and
`~/.local/state/callback/` (LangGraph SQLite checkpointer databases and logs).
```

with:

```
`--purge` deletes `~/.local/share/callback/` (application PDFs, JSON archives, and
LangGraph SQLite checkpointer databases) and `~/.local/state/callback/` (logs).
```

(Source of truth: checkpointer DBs live under `~/.local/share/callback/` per `apply_graph.py:37` / `profile_graph.py:31`.)

- [ ] **Step 6: Verify, run tests, commit, PR**

Run: `grep -rn "go-apply" CLAUDE.md AGENTS.md BRIEF.md README.md .env.example openspec/specs/ pyproject.toml`
Expected: every remaining match explicitly frames go-apply as deprecated/legacy/history — none normative.

Run: `uv run pytest -q`
Expected: 490 passed.

```bash
git add .env.example BRIEF.md openspec/specs/ pyproject.toml README.md
git commit -m "docs: sweep stale go-apply design references"
```

---

## Milestone 1 — Config consolidation (zero behavior change)



### Task 1.1: Move PASS_THRESHOLD into ScoringConfig

**Files:**
- Modify: `callback/scorer.py:122` (constant), `:51-83` (ScoringConfig), `:125-133` (ScoreResult), `:139-177` (score)
- Modify: `callback/apply_nodes.py:90-96` (_run_score)
- Test: `tests/test_scorer.py`

- [ ] **Step 1: Write the failing test**

Add to `tests/test_scorer.py` (match the file's existing class/function style):

```python
class TestPassThresholdConfig:
    def test_custom_pass_threshold_is_honored(self):
        cfg = scorer.ScoringConfig(pass_threshold=99.0)
        result = scorer.score("Experience\nPython work", ["Python"], [], cfg=cfg)
        assert result.pass_threshold == 99.0
        assert not result.passes()

    def test_default_config_threshold_is_70(self):
        assert scorer.DEFAULT_SCORING_CONFIG.pass_threshold == 70.0
```

- [ ] **Step 2: Run to verify failure**

Run: `uv run pytest tests/test_scorer.py -q -k "PassThreshold"`
Expected: FAIL — `ScoringConfig` has no `pass_threshold`; `DEFAULT_SCORING_CONFIG` undefined.

- [ ] **Step 3: Implement**

In `callback/scorer.py`:

1. Add to `ScoringConfig` (after `readability_penalty_per_filler`):
   ```python
       pass_threshold: float = 70.0
   ```
2. Delete the module constant line `PASS_THRESHOLD = 70.0` and add, directly after the `ScoringConfig` class definition:
   ```python
   # Shared default config — treat as frozen; construct a new ScoringConfig to customize.
   DEFAULT_SCORING_CONFIG = ScoringConfig()
   ```
3. Change `ScoreResult`:
   ```python
   @dataclass
   class ScoreResult:
       breakdown: ScoreBreakdown
       keywords: KeywordResult
       metric_bullets: list[str]
       filler_phrases: list[str]
       pass_threshold: float = 70.0

       def passes(self) -> bool:
           return self.breakdown.total() >= self.pass_threshold
   ```
4. In `score()`, replace `cfg = ScoringConfig()` (inside the `if cfg is None:` branch) with `cfg = DEFAULT_SCORING_CONFIG`, and add `pass_threshold=cfg.pass_threshold,` to the `ScoreResult(...)` construction.

In `callback/apply_nodes.py` `_run_score`, make the config explicit — add `cfg=scorer.DEFAULT_SCORING_CONFIG,` to the `scorer.score(...)` call.

- [ ] **Step 4: Fix any PASS_THRESHOLD importers**

Run: `grep -rn "PASS_THRESHOLD" callback/ tests/`
Expected: no remaining references (at baseline only `scorer.py` defines/uses it; if a test imports it, switch that test to `scorer.DEFAULT_SCORING_CONFIG.pass_threshold`).

- [ ] **Step 5: Run full suite + pyright**

Run: `uv run pytest -q && uv run pyright`
Expected: all pass, 0 errors (zero behavior change).

- [ ] **Step 6: Commit and PR**

```bash
git add callback/scorer.py callback/apply_nodes.py tests/test_scorer.py
git commit -m "feat: move pass threshold into ScoringConfig"
```

---

## Milestone 2 — Scorer bug fixes + engine version v2

First behavioral change — includes the version bump.

### Task 2.1: JDData — strip blank keywords, seniority "unspecified"

**Files:**
- Modify: `callback/jd_data.py:25` (SUPPORTED_SENIORITIES), `:52-64` (__post_init__)
- Test: `tests/test_jd_data.py`

- [ ] **Step 1: Write the failing tests**

Add to `tests/test_jd_data.py` (reuse the file's existing `PARTIAL_JD`-style fixtures):

```python
class TestKeywordCleaning:
    def test_blank_and_padded_keywords_are_cleaned(self):
        jd = JDData(title="T", company="C", required=[" Python ", "", "  "], preferred=["", "Go "])
        assert jd.model_dump()["required"] == ["Python"]
        assert jd.model_dump()["preferred"] == ["Go"]

    def test_all_blank_required_raises(self):
        with pytest.raises(JDDataError):
            JDData(title="T", company="C", required=["", "  "])

    def test_non_string_keyword_raises(self):
        with pytest.raises(JDDataError):
            JDData(title="T", company="C", required=["Python", 42])
```

Update the existing default-seniority test: rename `test_missing_or_empty_seniority_defaults_to_mid` to `test_missing_or_empty_seniority_becomes_unspecified` and change both assertions from `== "mid"` to `== "unspecified"`.

- [ ] **Step 2: Run to verify failure**

Run: `uv run pytest tests/test_jd_data.py -q`
Expected: the new/renamed tests FAIL (blank keywords pass through; default is "mid").

- [ ] **Step 3: Implement in `callback/jd_data.py`**

Change line 25:

```python
SUPPORTED_SENIORITIES = {"junior", "mid", "senior", "lead", "director", "unspecified"}
```

Replace `__post_init__` (and add the helper below it):

```python
    def __post_init__(self) -> None:
        if self.seniority in (None, ""):
            self.seniority = "unspecified"
        for field_name in ("required", "preferred", "key_responsibilities"):
            if not isinstance(getattr(self, field_name), list):
                raise JDDataError("invalid_jd", f"{field_name} must be a list")
        self.required = self._clean_keywords("required")
        self.preferred = self._clean_keywords("preferred")
        if not self.required:
            raise JDDataError("invalid_jd", "required skills must not be empty")
        if self.seniority not in SUPPORTED_SENIORITIES:
            raise JDDataError("invalid_jd", f"unsupported seniority: {self.seniority}")

    def _clean_keywords(self, field_name: str) -> list[str]:
        cleaned: list[str] = []
        for kw in getattr(self, field_name):
            if not isinstance(kw, str):
                raise JDDataError("invalid_jd", f"{field_name} entries must be strings")
            if kw.strip():
                cleaned.append(kw.strip())
        return cleaned
```

(Note: "unspecified" is an explicit honest state replacing the silent `"mid"` fallback. `Seniority` Literal and `EXTRACTION_PROTOCOL` stay unchanged — hosts still submit the 5-value vocabulary or omit.)

- [ ] **Step 4: Run and fix ripples**

Run: `uv run pytest -q`
Expected: any test that relied on the `"mid"` default fails — update those expectations to `"unspecified"` (check `tests/test_apply_graph.py:17`, `tests/test_apply_e2e.py:19,29`, `tests/test_server.py:29` — these set seniority explicitly, so they should already pass; fix only what fails).

- [ ] **Step 5: Commit**

```bash
git add callback/jd_data.py tests/
git commit -m "fix: strip blank keywords; replace silent mid-seniority fallback with unspecified"
```

### Task 2.2: Exclude contact lines from impact metrics

**Files:**
- Modify: `callback/scorer.py` (`_score_impact`, new regex near METRIC_RE)
- Test: `tests/test_scorer.py`

- [ ] **Step 1: Write the failing test**

```python
class TestImpactContactExclusion:
    def test_contact_lines_do_not_count_as_metrics(self):
        resume = (
            "Jane Doe\n"
            "555-867-5309 | jane@example.com | Austin, TX 78701\n"
            "linkedin.com/in/janedoe\n"
            "Experience\n"
            "- Reduced costs by 40%\n"
        )
        result = scorer.score(resume, ["Python"], [])
        assert result.metric_bullets == ["- Reduced costs by 40%"]
```

- [ ] **Step 2: Run to verify failure**

Run: `uv run pytest tests/test_scorer.py -q -k "ContactExclusion"`
Expected: FAIL — the phone/ZIP line appears in `metric_bullets`.

- [ ] **Step 3: Implement in `callback/scorer.py`**

Add below `YEAR_RE`:

```python
# Lines that are contact/header info, not accomplishment bullets — excluded
# from impact-metric detection so phone numbers and ZIP codes don't score.
CONTACT_LINE_RE = re.compile(
    r"(?i)(?:"
    r"\(?\b\d{3}\)?[-.\s]\d{3}[-.\s]\d{4}\b"  # phone: 555-867-5309, (415) 555-0100
    r"|[\w.+-]+@[\w-]+(?:\.[\w-]+)+"  # email
    r"|\bhttps?://|\bwww\."  # URLs
    r"|\b(?:linkedin|github)\.com/"  # profile links
    r"|(?-i:\b[A-Z]{2}\s+\d{5}(?:-\d{4})?\b)"  # state + ZIP: TX 78701
    r")"
)
```

In `_score_impact`, change the skip condition:

```python
        if not line or CONTACT_LINE_RE.search(line):
            continue
```

- [ ] **Step 4: Run full suite, fix pinned dicts**

Run: `uv run pytest -q`
Expected: tests whose fixture resumes contain contact lines may have pinned `impact_evidence`/`total`/`metric_bullets` values change — update those full dicts to the new correct values (verify by hand: each removed bullet is worth `1/5 × 10 = 2.0` impact points).

- [ ] **Step 5: Commit**

```bash
git add callback/scorer.py tests/
git commit -m "fix: exclude contact/header lines from impact-metric detection"
```

### Task 2.3: SCORING_ENGINE_VERSION = "v2" + mismatch note

**Files:**
- Modify: `callback/scorer.py` (new constant), `callback/apply_nodes.py:97-117` (_run_score dict), `:549-584` (report), `:619` (finalize)
- Test: `tests/test_scoring_engine.py`

- [ ] **Step 1: Write the failing tests**

```python
def test_run_score_stamps_engine_version():
    result = _run_score(
        RESUME_WITH_KEYWORDS,
        {"required": ["Python"], "preferred": ["AWS"], "required_years": 0.0},
    )
    assert result["scoring_engine_version"] == "v2"


def test_report_notes_engine_version_mismatch():
    state = ApplyState(
        session_id="s1",
        score_initial={"total": 50.0},  # no version key — pre-upgrade checkpoint
        score_final={"total": 60.0, "scoring_engine_version": "v2"},
    )
    result = report(state)
    assert any("engine version" in note for note in result["report"]["notes"])
```

- [ ] **Step 2: Run to verify failure**

Run: `uv run pytest tests/test_scoring_engine.py -q -k "engine_version"`
Expected: FAIL with KeyError / empty notes.

- [ ] **Step 3: Implement**

In `callback/scorer.py`, below the imports:

```python
SCORING_ENGINE_VERSION = "v2"
```

In `callback/apply_nodes.py` `_run_score`, add to the returned dict (after `"readability"`):

```python
        "scoring_engine_version": scorer.SCORING_ENGINE_VERSION,
```

In `report()`, after the `notes: list[str] = []` line, add:

```python
    si_version = si.get("scoring_engine_version")
    sf_version = sf.get("scoring_engine_version")
    if si_version != sf_version:
        notes.append(
            f"Scoring engine version changed mid-session ({si_version} -> {sf_version}); "
            "delta may be unreliable."
        )
```

In `finalize()`, replace `"scoring_engine_version": "v1",` with:

```python
            "scoring_engine_version": scorer.SCORING_ENGINE_VERSION,
```

- [ ] **Step 4: Run full suite, fix pinned dicts**

Run: `uv run pytest -q`
Expected: every full-dict `_run_score` assertion now needs `"scoring_engine_version": "v2"` added; finalize/archive tests expecting `"v1"` need `"v2"`. Update them.

Run: `uv run pyright`
Expected: 0 errors.

- [ ] **Step 5: Commit and PR**

```bash
git add callback/scorer.py callback/apply_nodes.py tests/
git commit -m "feat: stamp scoring engine version v2 and flag mid-session mismatches"
```

---

## Milestone 3 — Wire candidate years; not-evaluated semantics

The core fix: ExperienceFit stops being a constant.

### Task 3.1: Interval-merged years computation with skip logging

**Files:**
- Modify: `callback/apply_nodes.py:351-364` (_candidate_experience_years)
- Test: `tests/test_apply_nodes.py`

- [ ] **Step 1: Write the failing tests**

Add to `tests/test_apply_nodes.py` (import `_candidate_experience_years` from `callback.apply_nodes` and `ExperienceEntry` from `callback.section_map`):

```python
class TestCandidateExperienceYears:
    def test_overlapping_roles_do_not_double_count(self):
        experience = [
            ExperienceEntry(company="A", role="Eng", start_date="2020-01", end_date="2020-12"),
            ExperienceEntry(company="B", role="Eng", start_date="2020-06", end_date="2021-12"),
        ]
        # merged Jan 2020 – Dec 2021 = 24 months, not 12 + 19 = 31
        assert _candidate_experience_years(experience) == 2.0

    def test_disjoint_roles_sum(self):
        experience = [
            ExperienceEntry(company="A", role="Eng", start_date="2020-01", end_date="2020-06"),
            ExperienceEntry(company="B", role="Eng", start_date="2022-01", end_date="2022-06"),
        ]
        assert _candidate_experience_years(experience) == 1.0

    def test_all_unparseable_returns_none(self):
        experience = [ExperienceEntry(company="A", role="Eng", start_date="??", end_date=None)]
        assert _candidate_experience_years(experience) is None
```

- [ ] **Step 2: Run to verify failure**

Run: `uv run pytest tests/test_apply_nodes.py -q -k "CandidateExperienceYears"`
Expected: first test FAILS (current code sums to 31 months → 2.58).

- [ ] **Step 3: Replace the implementation**

```python
def _candidate_experience_years(experience) -> float | None:
    intervals: list[tuple[int, int]] = []
    skipped = 0
    for exp in experience:
        start = _parse_resume_month(exp.start_date)
        end = _parse_resume_month(exp.end_date)
        if not start or not end:
            skipped += 1
            continue
        start_index = start[0] * 12 + start[1]
        end_index = end[0] * 12 + end[1]
        if end_index >= start_index:
            intervals.append((start_index, end_index))
    if skipped:
        logger.warning(
            json.dumps(
                {
                    "event": "experience_years_entries_skipped",
                    "skipped": skipped,
                    "parsed": len(intervals),
                }
            )
        )
    if not intervals:
        return None
    intervals.sort()
    months = 0
    cur_start, cur_end = intervals[0]
    for start_index, end_index in intervals[1:]:
        if start_index <= cur_end:
            cur_end = max(cur_end, end_index)
        else:
            months += cur_end - cur_start + 1
            cur_start, cur_end = start_index, end_index
    months += cur_end - cur_start + 1
    return round(months / 12, 2)
```

- [ ] **Step 4: Run and commit**

Run: `uv run pytest -q`
Expected: all pass (render-warning tests using this helper keep working; fix any pinned years values that assumed double-counting).

```bash
git add callback/apply_nodes.py tests/test_apply_nodes.py
git commit -m "fix: merge overlapping date ranges in candidate-years computation"
```

### Task 3.2: Scorer v2 — years-only ExperienceFit, None + renormalization

**Files:**
- Modify: `callback/scorer.py` (ScoringConfig, ScoreBreakdown, score, _score_experience)
- Test: `tests/test_scorer.py`

- [ ] **Step 1: Write the failing tests**

```python
class TestExperienceFitV2:
    RESUME = "Experience\nPython work\nEducation\nB.S.\nSkills\nPython"

    def test_not_evaluated_when_no_required_years(self):
        result = scorer.score(self.RESUME, ["Python"], [], required_years=0.0)
        assert result.breakdown.experience_fit is None

    def test_not_evaluated_when_candidate_years_unknown(self):
        result = scorer.score(self.RESUME, ["Python"], [], required_years=5.0)
        assert result.breakdown.experience_fit is None

    def test_partial_years_credit(self):
        result = scorer.score(
            self.RESUME, ["Python"], [], candidate_years=5.0, required_years=10.0
        )
        # years-only: 5/10 = 0.5 → 0.5 × 25.0 (M3 weight) = 12.5
        assert result.breakdown.experience_fit == 12.5

    def test_negative_candidate_years_clamps_to_zero(self):
        result = scorer.score(
            self.RESUME, ["Python"], [], candidate_years=-3.0, required_years=5.0
        )
        assert result.breakdown.experience_fit == 0.0

    def test_overqualification_penalty(self):
        result = scorer.score(
            self.RESUME, ["Python"], [], candidate_years=25.0, required_years=10.0
        )
        # capped 1.0 × 0.85 penalty × 25.0 = 21.25
        assert result.breakdown.experience_fit == 21.25

    def test_total_renormalizes_when_not_evaluated(self):
        result = scorer.score(self.RESUME, ["Python"], [], required_years=0.0)
        b = result.breakdown
        base = b.keyword_match + b.impact_evidence + b.ats_format + b.readability
        assert b.total() == base * (100.0 / 75.0)  # exp weight is 25.0 until M4

    def test_unknown_seniority_kwarg_is_gone(self):
        with pytest.raises(TypeError):
            scorer.score(self.RESUME, ["Python"], [], seniority_match="exact")
```

- [ ] **Step 2: Run to verify failure**

Run: `uv run pytest tests/test_scorer.py -q -k "ExperienceFitV2"`
Expected: FAIL across the board (old signature/semantics).

- [ ] **Step 3: Implement in `callback/scorer.py`**

1. In `ScoringConfig`, **delete** these three fields entirely: `experience_seniority_weight`, `experience_years_weight`, `seniority_multipliers`.
2. Replace `ScoreBreakdown`:
   ```python
   @dataclass
   class ScoreBreakdown:
       keyword_match: float
       experience_fit: float | None
       impact_evidence: float
       ats_format: float
       readability: float
       renorm_factor: float = 1.0  # > 1.0 only when experience_fit is not evaluated
       ats_diagnostics: list[ATSHeaderDiagnostic] = field(default_factory=list)

       def total(self) -> float:
           base = self.keyword_match + self.impact_evidence + self.ats_format + self.readability
           if self.experience_fit is None:
               return base * self.renorm_factor
           return base + self.experience_fit
   ```
3. Replace `_score_experience`:
   ```python
   def _score_experience(
       candidate_years: float | None,
       required_years: float,
       cfg: ScoringConfig,
   ) -> float | None:
       """Return experience-fit points, or None when the dimension cannot be evaluated."""
       if required_years <= 0 or candidate_years is None:
           return None
       years = max(candidate_years, 0.0)
       years_score = min(years / required_years, 1.0)
       if years > required_years * cfg.overqualification_threshold_mult:
           years_score *= cfg.overqualification_penalty
       return years_score * cfg.weights.experience_fit
   ```
4. Update `score()` — new signature and body changes:
   ```python
   def score(
       resume_text: str,
       required: list[str],
       preferred: list[str],
       candidate_years: float | None = None,
       required_years: float = 0.0,
       cfg: ScoringConfig | None = None,
       closeable_by: Literal["tailor", "render", "source_pdf"] = "source_pdf",
   ) -> ScoreResult:
       """Score resume_text against LLM-extracted JD keywords.

       All inputs are caller-supplied; this function has no I/O or side effects.
       ExperienceFit is years-only: evaluated when required_years > 0 and
       candidate_years is known, otherwise None — the total then renormalizes
       over the remaining dimensions so the scale stays 0–100.
       closeable_by is forwarded to _score_ats() to tag ATS diagnostics.
       """
   ```
   In the body, replace the `exp_score = ...` line with:
   ```python
       exp_score = _score_experience(candidate_years, required_years, cfg)
       w = cfg.weights
       full_max = w.keyword_match + w.experience_fit + w.impact_evidence + w.ats_format + w.readability
       renorm = full_max / (full_max - w.experience_fit) if exp_score is None else 1.0
   ```
   and add `renorm_factor=renorm,` to the `ScoreBreakdown(...)` construction.

- [ ] **Step 4: Run, then run pyright**

Run: `uv run pytest tests/test_scorer.py -q -k "ExperienceFitV2" && uv run pyright callback/scorer.py`
Expected: tests PASS; pyright clean. (Full suite still broken until Task 3.3 — that's expected.)

- [ ] **Step 5: Commit**

```bash
git add callback/scorer.py tests/test_scorer.py
git commit -m "feat!: years-only ExperienceFit with explicit not-evaluated renormalization"
```

### Task 3.3: Thread candidate_years through state, nodes, and report

**Files:**
- Modify: `callback/state.py:46-74` (ApplyState), `callback/apply_nodes.py` (parse_initial, _run_score, score_initial, score_final, report)
- Test: `tests/test_scoring_engine.py`, `tests/test_apply_nodes.py`

- [ ] **Step 1: Write the failing tests**

In `tests/test_scoring_engine.py`, replace `test_required_years_reduces_experience_fit` with:

```python
    def test_experience_evaluated_with_candidate_years(self):
        kws = {"required": ["ZZZNONEXISTENT"], "preferred": [], "required_years": 10.0}
        result = _run_score("some resume text", kws, candidate_years=5.0)
        expected = {
            "total": 10.0 + 12.5,  # readability 10.0 + exp 0.5 × 25.0
            "keyword_match": 0.0,
            "experience_fit": 12.5,
            "experience_evaluated": True,
            "impact_evidence": 0.0,
            "ats_format": 0.0,
            "readability": 10.0,
            "req_matched": [],
            "req_unmatched": ["ZZZNONEXISTENT"],
            "pref_matched": [],
            "pref_unmatched": [],
            "scoring_engine_version": "v2",
            "ats_diagnostics": _expected_ats_diagnostics(matched=False),
        }
        assert result == expected

    def test_experience_not_evaluated_without_candidate_years(self):
        kws = {"required": ["ZZZNONEXISTENT"], "preferred": [], "required_years": 10.0}
        result = _run_score("some resume text", kws)
        assert result["experience_fit"] is None
        assert result["experience_evaluated"] is False
        assert result["total"] == 10.0 * (100.0 / 75.0)  # readability only, renormalized
```

Add a report test:

```python
def test_report_delta_skips_unevaluated_experience():
    score = {
        "total": 40.0, "keyword_match": 30.0, "experience_fit": None,
        "experience_evaluated": False, "impact_evidence": 0.0,
        "ats_format": 0.0, "readability": 10.0,
        "scoring_engine_version": "v2", "ats_diagnostics": [],
    }
    state = ApplyState(session_id="s1", score_initial=score, score_final={**score, "total": 50.0, "keyword_match": 40.0})
    result = report(state)
    assert result["report"]["delta"]["experience_fit"] is None
    assert result["report"]["delta"]["keyword_match"] == 10.0
    assert result["report"]["experience_evaluated"] is False
    assert any("not evaluated" in note for note in result["report"]["notes"])
```

- [ ] **Step 2: Run to verify failure**

Run: `uv run pytest tests/test_scoring_engine.py -q`
Expected: FAIL — `_run_score` has no `candidate_years` parameter; delta coerces None to 0.

- [ ] **Step 3: Implement**

In `callback/state.py`, add to `ApplyState` (after `sections`):

```python
    candidate_years: float | None = Field(default=None)
```

In `callback/apply_nodes.py`:

1. `parse_initial` — replace the `base` construction:
   ```python
       if sections_json:
           section_map = SectionMap.model_validate_json(sections_json)
           base = {
               "sections": section_map.model_dump(),
               "wiki_index": wiki_index,
               "candidate_years": _candidate_experience_years(section_map.experience),
           }
   ```
2. `_run_score` — new signature and call:
   ```python
   def _run_score(
       text: str | None,
       keywords: dict | None,
       closeable_by: str = "source_pdf",
       candidate_years: float | None = None,
   ) -> dict:
       if not text or not text.strip():
           raise ValueError("_run_score: text must not be empty")
       if not keywords or not keywords.get("required"):
           raise ValueError("_run_score: keywords['required'] must be non-empty")
       r = scorer.score(
           text,
           keywords["required"],
           keywords["preferred"],
           candidate_years=candidate_years,
           required_years=keywords["required_years"],
           cfg=scorer.DEFAULT_SCORING_CONFIG,
           closeable_by=closeable_by,  # type: ignore[arg-type]
       )
   ```
   and in the returned dict, after `"experience_fit"`:
   ```python
           "experience_evaluated": r.breakdown.experience_fit is not None,
   ```
3. `score_initial` / `score_final` — pass the state value:
   ```python
       return {
           "score_initial": _run_score(
               state.parsed_initial,
               state.keywords,
               closeable_by="source_pdf",
               candidate_years=state.candidate_years,
           )
       }
   ```
   (and the mirror-image change in `score_final` with `closeable_by="render"`).
4. `report` — replace the delta line with:
   ```python
       delta = {dim: _dim_delta(si, sf, dim) for dim in _SCORE_DIMS}
   ```
   adding this helper above `report()`:
   ```python
   def _dim_delta(si: dict, sf: dict, dim: str) -> float | None:
       before, after = si.get(dim), sf.get(dim)
       if before is None or after is None:
           return None
       return round(after - before, 2)
   ```
   After the version-mismatch note block, add:
   ```python
       if sf.get("experience_evaluated") is False:
           notes.append(
               "Experience fit not evaluated (JD states no years requirement or resume "
               "dates are unavailable); total is renormalized over the remaining dimensions."
           )
   ```
   And add to the returned `"report"` dict (after `"no_coverage"`):
   ```python
               "experience_evaluated": sf.get("experience_evaluated"),
   ```

- [ ] **Step 4: Update all remaining pinned test dicts**

Run: `uv run pytest -q`
Expected: failures concentrated in `tests/test_scoring_engine.py`, `tests/test_score_roundtrip.py`, `tests/test_apply_graph.py`, `tests/test_apply_e2e.py`. Transformation rule for every pinned full dict where `required_years` is 0 or candidate years were never supplied: `experience_fit` becomes `None`, add `"experience_evaluated": False`, and `total = (keyword_match + impact_evidence + ats_format + readability) × 100/75`. Worked example — `TestRunScore::test_returns_full_breakdown` (kw 45.0, impact 4.0, ats 10.0, read 10.0): base 69.0 → total `92.0`, `experience_fit: None`. Every dict also needs `"experience_evaluated"` and `"scoring_engine_version"` keys (added in M2).

Run: `uv run pytest -q && uv run pyright`
Expected: all pass, 0 errors.

- [ ] **Step 5: Commit and PR**

```bash
git add callback/state.py callback/apply_nodes.py tests/
git commit -m "feat: wire candidate years from parse_initial into both score runs"
```

---

## Milestone 4 — Reweight 55/15/10/10/10 + knockout warnings



### Task 4.1: Reweight

**Files:**
- Modify: `callback/scorer.py:42-48` (ScoringWeights)
- Test: existing pinned dicts across `tests/`

- [ ] **Step 1: Change the defaults**

```python
@dataclass
class ScoringWeights:
    keyword_match: float = 55.0
    experience_fit: float = 15.0
    impact_evidence: float = 10.0
    ats_format: float = 10.0
    readability: float = 10.0
```

- [ ] **Step 2: Update pinned expectations**

Run: `uv run pytest -q`
Transformation rule: full-coverage keyword score is now 55.0 (was 45.0); evaluated experience scales by 15/25 (e.g. 12.5 → 7.5, 21.25 → 12.75); not-evaluated renormalization factor becomes `100/85`. Worked example — `test_returns_full_breakdown`: kw 55.0 + impact 4.0 + ats 10.0 + read 10.0 = base 79.0 → total `79.0 * 100.0 / 85.0` (pin the exact float Python prints: `92.94117647058823`). Also update the M3 tests that pinned the 25.0 weight (`test_partial_years_credit` → 7.5, `test_overqualification_penalty` → 12.75, renorm test comment → 100/85).

Run: `uv run pytest -q`
Expected: all pass.

- [ ] **Step 3: Commit**

```bash
git add callback/scorer.py tests/
git commit -m "feat!: reweight scoring to 55/15/10/10/10"
```

### Task 4.2: Knockout warnings in report

**Files:**
- Modify: `callback/apply_nodes.py` (report)
- Test: `tests/test_scoring_engine.py`

- [ ] **Step 1: Write the failing tests**

```python
def _score_stub(**overrides) -> dict:
    base = {
        "total": 50.0, "keyword_match": 40.0, "experience_fit": 7.5,
        "experience_evaluated": True, "impact_evidence": 0.0,
        "ats_format": 0.0, "readability": 10.0,
        "scoring_engine_version": "v2", "ats_diagnostics": [],
    }
    return {**base, **overrides}


class TestKnockoutWarnings:
    def _report(self, candidate_years, required_years):
        state = ApplyState(
            session_id="s1",
            candidate_years=candidate_years,
            keywords={"required": ["Python"], "preferred": [], "required_years": required_years},
            score_initial=_score_stub(),
            score_final=_score_stub(),
        )
        return report(state)["report"]["warnings"]

    def test_any_shortfall_warns_likely(self):
        warnings = self._report(candidate_years=7.0, required_years=8.0)
        assert len(warnings) == 1
        assert warnings[0].startswith("LIKELY KNOCKOUT")

    def test_double_gap_warns_strong(self):
        warnings = self._report(candidate_years=4.0, required_years=8.0)
        assert len(warnings) == 1
        assert warnings[0].startswith("STRONG KNOCKOUT RISK")

    def test_meeting_years_no_warning(self):
        assert self._report(candidate_years=9.0, required_years=8.0) == []

    def test_unknown_years_no_warning(self):
        assert self._report(candidate_years=None, required_years=8.0) == []
```

- [ ] **Step 2: Run to verify failure**

Run: `uv run pytest tests/test_scoring_engine.py -q -k "Knockout"`
Expected: FAIL — report has no `warnings` key.

- [ ] **Step 3: Implement in `report()`**

After the notes block, add:

```python
    warnings: list[str] = []
    required_years = float((state.keywords or {}).get("required_years") or 0.0)
    if (
        required_years > 0
        and state.candidate_years is not None
        and state.candidate_years < required_years
    ):
        strong = required_years >= 2 * state.candidate_years
        label = "STRONG KNOCKOUT RISK" if strong else "LIKELY KNOCKOUT"
        message = (
            f"{label}: JD requires {required_years:g}+ years; resume shows "
            f"{state.candidate_years:g}. Years screener questions are typically "
            "binary pass/fail."
        )
        if strong:
            message += " Consider whether to apply."
        warnings.append(message)
```

and add to the returned `"report"` dict (after `"notes"`):

```python
            "warnings": warnings,
```

- [ ] **Step 4: Run full suite, fix report-shape dicts**

Run: `uv run pytest -q && uv run pyright`
Expected: tests pinning the full report dict need `"warnings": []` added. All pass, 0 errors.

- [ ] **Step 5: Update CLAUDE.md scoring table and commit/PR**

In `CLAUDE.md`, replace the scoring table rows:

```
| KeywordMatch    | 45  | Required (0.7) + preferred (0.3) keywords |
| ExperienceFit   | 25  | Years met + seniority match               |
```

with:

```
| KeywordMatch    | 55  | Required (0.7) + preferred (0.3) keywords |
| ExperienceFit   | 15  | Years met (years-only; `None` + renormalization when not evaluable) |
```

Make the same table fix in `AGENTS.md` (search for `| KeywordMatch`).

```bash
git add callback/apply_nodes.py tests/ CLAUDE.md AGENTS.md
git commit -m "feat: two-tier years knockout warnings in report"
```

---

## Milestone 5 — Matcher normalization + golden determinism test



### Task 5.1: Slash-spacing normalization

**Files:**
- Modify: `callback/scorer.py` (_normalize_for_match)
- Test: `tests/test_scorer.py`

- [ ] **Step 1: Write the failing test**

```python
class TestMatcherNormalization:
    def test_slash_spacing_variants_match(self):
        result = scorer.score("Experience\nBuilt CI / CD pipelines", ["CI/CD"], [])
        assert result.keywords.req_matched == ["CI/CD"]
```

- [ ] **Step 2: Run to verify failure**

Run: `uv run pytest tests/test_scorer.py -q -k "slash_spacing"`
Expected: FAIL — "CI/CD" doesn't match "CI / CD".

- [ ] **Step 3: Implement**

Add next to `_DASH_RE`:

```python
_SLASH_WS_RE = re.compile(r"\s*/\s*")
```

and in `_normalize_for_match`, after the dash substitution:

```python
    text = _SLASH_WS_RE.sub("/", text)
```

(Do **not** touch the duplicate `_normalize_for_match` in `apply_nodes.py` — it serves tailor diagnostics and is queued for the `wiki-ingest` dedup.)

- [ ] **Step 4: Run and commit**

Run: `uv run pytest -q`
Expected: all pass.

```bash
git add callback/scorer.py tests/test_scorer.py
git commit -m "feat: normalize slash spacing in keyword matching"
```

### Task 5.2: Conservative plural tolerance

**Files:**
- Modify: `callback/scorer.py` (_compile_keyword_pattern + helper)
- Test: `tests/test_scorer.py`

- [ ] **Step 1: Write the failing tests**

Add to `TestMatcherNormalization`:

```python
    def test_singular_keyword_matches_plural_resume(self):
        result = scorer.score("Experience\nBuilt containers at scale", ["container"], [])
        assert result.keywords.req_matched == ["container"]

    def test_plural_keyword_matches_singular_resume(self):
        result = scorer.score("Experience\nDesigned each microservice", ["microservices"], [])
        assert result.keywords.req_matched == ["microservices"]

    def test_short_tokens_get_no_plural_tolerance(self):
        result = scorer.score("Experience\nUsed AWSX tooling", ["AWS"], [])
        assert result.keywords.req_matched == []

    def test_no_abbreviation_expansion(self):
        result = scorer.score("Experience\nManaged Kubernetes clusters", ["k8s"], [])
        assert result.keywords.req_matched == []

    def test_trailing_s_words_still_match_themselves(self):
        result = scorer.score("Experience\nTuned Redis and Jenkins", ["Redis", "Jenkins"], [])
        assert result.keywords.req_matched == ["Redis", "Jenkins"]
```

- [ ] **Step 2: Run to verify failure**

Run: `uv run pytest tests/test_scorer.py -q -k "MatcherNormalization"`
Expected: the two plural tests FAIL; the guard tests pass.

- [ ] **Step 3: Implement**

Replace `_compile_keyword_pattern` and add the helper:

```python
_PLURAL_MIN_STEM = 4


def _plural_tolerant(token: str) -> str:
    """Regex fragment matching token with optional trailing s/es.

    Conservative by design: alpha-only tokens with a stem of >= 4 chars.
    Honest-signal rule — a recruiter's literal search for the JD term must
    still retrieve the resume; no synonym or abbreviation expansion.
    """
    if not token.isalpha() or len(token) < _PLURAL_MIN_STEM:
        return re.escape(token)
    stem = token[:-1] if token.endswith("s") and not token.endswith("ss") else token
    if len(stem) < _PLURAL_MIN_STEM:
        return re.escape(token)
    return re.escape(stem) + r"(?:e?s)?"


def _compile_keyword_pattern(kw: str) -> re.Pattern:
    prefix = r"\b" if kw and _is_word_char(kw[0]) else ""
    suffix = r"\b" if kw and _is_word_char(kw[-1]) else ""
    head, sep, last = kw.rpartition(" ")
    body = re.escape(head + sep) + _plural_tolerant(last)
    return re.compile(f"(?i){prefix}{body}{suffix}")
```

- [ ] **Step 4: Run full suite**

Run: `uv run pytest -q && uv run pyright`
Expected: all pass (plural tolerance only widens matches for ≥4-char alpha tokens; fix any pinned keyword test that intentionally relied on singular/plural mismatch).

- [ ] **Step 5: Commit**

```bash
git add callback/scorer.py tests/test_scorer.py
git commit -m "feat: conservative trailing-s plural tolerance in keyword matching"
```

### Task 5.3: Golden determinism test

**Files:**
- Test: `tests/test_scorer.py`

- [ ] **Step 1: Write the test scaffold with a capture helper**

```python
from dataclasses import asdict
from pathlib import Path

FIXTURES = Path(__file__).parent / "fixtures"

GOLDEN_REQUIRED = ["Python", "AWS", "Docker", "Kubernetes", "CI/CD"]
GOLDEN_PREFERRED = ["Terraform", "GraphQL"]


def _golden_score() -> dict:
    resume = (FIXTURES / "sample_resume.txt").read_text()
    return asdict(
        scorer.score(
            resume,
            GOLDEN_REQUIRED,
            GOLDEN_PREFERRED,
            candidate_years=5.5,
            required_years=4.0,
        )
    )


class TestGoldenDeterminism:
    def test_repeated_calls_are_identical(self):
        assert _golden_score() == _golden_score()

    def test_pinned_golden_values(self):
        assert _golden_score() == GOLDEN_EXPECTED
```

- [ ] **Step 2: Capture the golden values**

Run: `uv run python -c "from tests.test_scorer import _golden_score; import pprint; pprint.pprint(_golden_score())"`
Paste the printed dict verbatim into `tests/test_scorer.py` as `GOLDEN_EXPECTED = {...}` (placed above the test class). Eyeball-verify the headline numbers by hand: `keyword_match` should equal `(req_pct × 0.7 + pref_pct × 0.3) × 55.0` for the match counts printed, and `experience_fit` should be `min(5.5/4.0, 1.0) × 15.0 = 15.0`.

- [ ] **Step 3: Run to verify pass**

Run: `uv run pytest tests/test_scorer.py -q -k "Golden"`
Expected: 2 passed. (This pins scorer-only behavior on fixed text. Do NOT golden-test `score_final` — its Chromium-extraction input is environment-pinned.)

- [ ] **Step 4: Final verification, commit, PR**

Run: `uv run pytest -q && uv run pyright`
Expected: all pass, 0 errors.

```bash
git add tests/test_scorer.py
git commit -m "test: golden determinism test pinning scorer v2 on fixtures"
```

---

## Completion checklist

- [ ] Single PR from `feat/scoring-redesign-v2` to `main` containing all milestones (everything ships together, so the v2 tag is consistent):
  `gh pr create --title "feat: scoring redesign v2 (standalone, honest ExperienceFit)" --fill`
- [ ] `grep -rn "go-apply" --include="*.md" .` shows only deprecated/legacy/history framing.
- [ ] `uv run pytest -q` green; `uv run pyright` 0 errors on `main`.
- [ ] Smoke check: `uv run python scripts/smoke_apply.py` still completes end-to-end.
