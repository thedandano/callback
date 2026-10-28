# AI Filler Readability (#147) Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Penalize generic AI buzzphrases in the deterministic Readability dimension using the existing filler-phrase −2/hit rule, without a new scoring dimension or LLM-as-judge.

**Architecture:** Extend `ScoringConfig.filler_phrases` with a short list of AI-style buzzphrases from issue #147 triage. Matching stays case-insensitive word-boundary search in `_score_readability`. Optionally reinforce “facts first / don't invent” in `_TAILOR_INSTRUCTIONS` (already partly present after #146).

**Tech Stack:** Python, `callback/scorer.py`, pytest (`tests/test_scorer.py`), optional copy in `callback/server.py` / skill.

## Global Constraints

- Do **not** invent a new scoring dimension — use existing Readability + `readability_penalty_per_filler` (2.0).
- Do **not** add LLM-as-judge or semantic “AI-sounding” detection.
- Keep scoring pure and deterministic (constitution).
- Filler list stays short: triage examples plus close cousins already named in the video / existing tailor bans that are distinctive AI buzz — not every banned verb.
- Exact phrases to add (lowercase, as stored in config):
  - `spearheaded`
  - `cross-functional`
  - `operational excellence`
  - `results-driven`
  - `proven track record`
  - `results-oriented` (close cousin already banned in tailor summary copy)
- Do **not** add bare `driven` (too broad; would hit honest “data-driven” / “event-driven”).
- Do **not** change KeywordMatch, ExperienceFit, ImpactEvidence, or ATSFormat weights.
- Story S/B/I intake: no change.
- Score-changing change: document in CHANGELOG; Morgan Reyes fixtures contain `cross-functional` and will lose 2 Readability points once when that phrase is present — expected.

---

## File Structure

| File | Responsibility |
|------|----------------|
| `callback/scorer.py` | Default `filler_phrases` list in `ScoringConfig` |
| `tests/test_scorer.py` | Lock detection + −2 penalty for new AI fillers |
| `callback/server.py` | Optional one-line facts-first reinforce in `_TAILOR_INSTRUCTIONS` |
| `skills/tailor-resume/SKILL.md` | Optional align with facts-first / interview test |
| `CHANGELOG.md` | Unreleased note: score-changing Readability fillers |

---

### Task 1: Add AI buzzphrases to `filler_phrases` + tests

**Files:**
- Modify: `callback/scorer.py:78-89` (`ScoringConfig.filler_phrases`)
- Modify: `tests/test_scorer.py` (extend readability/filler tests around existing `test_filler_phrase_detected` ~358)

**Interfaces:**
- Consumes: `_score_readability(resume_text, cfg)` — already matches each `cfg.filler_phrases` entry with `(?i)\b...\b` after `normalize_for_match`
- Produces: default config that detects the six new phrases; duty-style fillers unchanged

- [ ] **Step 1: Write the failing tests**

Add to `tests/test_scorer.py` (same class / module as existing filler tests):

```python
    def test_ai_buzzphrase_fillers_detected(self):
        resume = (
            "Spearheaded cross-functional initiatives to drive operational excellence. "
            "Results-driven professional with a proven track record of success. "
            "Results-oriented leader."
        )
        result = score(resume, required=[], preferred=[])
        for phrase in (
            "spearheaded",
            "cross-functional",
            "operational excellence",
            "results-driven",
            "proven track record",
            "results-oriented",
        ):
            assert phrase in result.filler_phrases, phrase

    def test_ai_buzzphrase_fillers_penalize_readability(self):
        cfg = DEFAULT_SCORING_CONFIG
        resume = "Spearheaded delivery of operational excellence with a proven track record."
        result = score(resume, required=[], preferred=[])
        # three distinct phrases: spearheaded, operational excellence, proven track record
        expected = max(
            cfg.weights.readability - 3 * cfg.readability_penalty_per_filler,
            0.0,
        )
        assert result.breakdown.readability == pytest.approx(expected)
        assert set(result.filler_phrases) >= {
            "spearheaded",
            "operational excellence",
            "proven track record",
        }

    def test_event_driven_not_flagged_as_results_driven(self):
        result = score(
            "Built event-driven pipelines and a data-driven dashboard.",
            required=[],
            preferred=[],
        )
        assert "results-driven" not in result.filler_phrases
        assert "driven" not in result.filler_phrases
```

Import `DEFAULT_SCORING_CONFIG` from `callback.scorer` if not already imported in the test file.

- [ ] **Step 2: Run tests to verify they fail**

Run:

```bash
uv run pytest \
  tests/test_scorer.py::TestReadability::test_ai_buzzphrase_fillers_detected \
  tests/test_scorer.py::TestReadability::test_ai_buzzphrase_fillers_penalize_readability \
  tests/test_scorer.py::TestReadability::test_event_driven_not_flagged_as_results_driven \
  -v
```

If the class name differs, discover with:

```bash
uv run pytest tests/test_scorer.py -q --collect-only 2>/dev/null | rg -i 'filler|readability'
```

Use the real class/node ids. Expected: FAIL because new phrases are not in `filler_phrases` yet (`test_event_driven...` may PASS already — that is fine).

- [ ] **Step 3: Write minimal implementation**

In `callback/scorer.py`, replace the `filler_phrases` default list with:

```python
    filler_phrases: list[str] = field(
        default_factory=lambda: [
            "responsible for",
            "worked on",
            "helped with",
            "assisted in",
            "involved in",
            "participated in",
            "contributed to",
            "familiar with",
            "exposure to",
            "knowledge of",
            # AI / buzzphrase fillers (issue #147) — same −2/hit Readability rule
            "spearheaded",
            "cross-functional",
            "operational excellence",
            "results-driven",
            "proven track record",
            "results-oriented",
        ]
    )
```

Do not change `readability_penalty_per_filler` or `_score_readability`.

- [ ] **Step 4: Run tests to verify they pass**

Run the three new tests plus existing filler tests:

```bash
uv run pytest tests/test_scorer.py -k 'filler or readability or ai_buzz' -v
```

Expected: PASS for new + existing filler tests.

- [ ] **Step 5: Commit**

```bash
git add callback/scorer.py tests/test_scorer.py
git commit -m "$(cat <<'EOF'
feat: penalize AI buzzphrases in Readability fillers

Issue #147: extend filler_phrases with spearheaded, cross-functional,
operational excellence, results-driven, proven track record, results-oriented.
Same −2/hit rule; no new dimension.
EOF
)"
```

---

### Task 2: Optional facts-first tailor reinforce + CHANGELOG

**Files:**
- Modify: `callback/server.py` (`_TAILOR_INSTRUCTIONS`)
- Modify: `skills/tailor-resume/SKILL.md` (Tailoring Rules)
- Modify: `CHANGELOG.md` (Unreleased)
- Modify: `tests/test_server.py` (assert new phrase if instructions change)

**Interfaces:**
- Consumes: existing `_TAILOR_INSTRUCTIONS` returned as `data.tailor_instructions`
- Produces: one explicit facts-first / interview-test line; CHANGELOG documents score-changing Readability

- [ ] **Step 1: Write failing assertion for tailor copy**

In `tests/test_server.py`, extend an existing test that already reads `data.tailor_instructions` (e.g. `test_submit_keywords_tailor_instructions_include_project_guidance`) with:

```python
        "mentions_facts_first": "facts first" in instructions.lower()
        or "without changing any facts" in instructions.lower()
        or "interview" in instructions.lower(),
```

expected `True`. Prefer asserting a single distinctive phrase that Step 3 will add verbatim, e.g. `"without changing any facts" in instructions`.

- [ ] **Step 2: Run test to verify it fails**

Run the chosen test with `-v`. Expected: FAIL on the new key.

- [ ] **Step 3: Add facts-first bullet and CHANGELOG**

Add this bullet to `_TAILOR_INSTRUCTIONS` immediately after the Skills line (before Keyword mapping):

```python
    "- Facts first: base every edit on wiki or resume evidence; polish wording "
    "without changing any facts. Keep only wording you could explain in an interview.\n"
```

In `skills/tailor-resume/SKILL.md` Tailoring Rules, add after the mapping bullets:

```markdown
- Facts first: polish wording without changing any facts. Keep only wording you could explain in an interview.
```

Under `CHANGELOG.md` `## Unreleased`:

```markdown
- Readability: treat AI buzzphrases (spearheaded, cross-functional, operational
  excellence, results-driven, proven track record, results-oriented) as filler
  (−2 each, existing rule). Score-changing for resumes that use those phrases (#147).
```

- [ ] **Step 4: Run tests**

```bash
uv run pytest \
  tests/test_scorer.py -k 'filler or ai_buzz' \
  tests/test_server.py::test_submit_keywords_tailor_instructions_include_project_guidance \
  -v
```

Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add callback/server.py skills/tailor-resume/SKILL.md CHANGELOG.md tests/test_server.py
git commit -m "$(cat <<'EOF'
docs: facts-first tailor note and #147 CHANGELOG

Reinforce polish-without-changing-facts; document score-changing fillers.
EOF
)"
```

---

## Self-Review

1. **Spec coverage:** Triage accept (filler list + optional facts-first) → Tasks 1–2. Skip LLM-as-judge → Global Constraints. No story intake changes.
2. **Placeholder scan:** Exact phrases, test code, and commands are concrete. Class name discovery noted where pytest node ids may differ.
3. **Type consistency:** No new types; only list extensions and string copy. Bare `driven` explicitly excluded to avoid false positives on `event-driven` / `data-driven`.
