# Keyword Mapping Handoff (#146) Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Strengthen tailor / pass-2 host handoff so hosts map JD keywords to evidenced experience (problems first) instead of stuffing, without changing KeywordMatch scoring.

**Architecture:** Protocol/handoff-only change. `_TAILOR_INSTRUCTIONS` and the post-pass-2 `host_task` tell the host to treat `key_responsibilities` as employer problems, map only evidenced keywords, and leave unsupported gaps uncovered. The scorer stays linear presence-only KeywordMatch. Pass-2 responsibilities remain unscored.

**Tech Stack:** Python, FastMCP tool envelopes in `callback/server.py`, pytest, existing tailor-resume skill + evals runner prompt text.

## Global Constraints

- Do **not** change `callback/scorer.py`, KeywordMatch weights, or add density/coverage penalties.
- Do **not** score `key_responsibilities` / pass-2 terms.
- Scope is protocol/handoff/skill/eval-prompt copy only (issue #146 triage: partial accept).
- Keep existing anti-fabrication / project-edit rules; extend them, do not remove them.
- Scoring remains pure and deterministic (constitution).
- Prefer fewer strong evidenced edits over maximum keyword coverage (copy must say this explicitly).

---

## File Structure

| File | Responsibility |
|------|----------------|
| `callback/server.py` | `_TAILOR_INSTRUCTIONS` and `_submit_keywords_workflow` host_task strings the host reads before editing |
| `tests/test_server.py` | Assert new mapping / anti-stuffing phrases appear in tool replies |
| `skills/tailor-resume/SKILL.md` | Host-facing skill rules aligned with the same mapping guidance |
| `evals/runner.py` | E2 tailor prompt bullets aligned with `_TAILOR_INSTRUCTIONS` (runner already imports it) |
| `CHANGELOG.md` | Unreleased note for the handoff strengthening |

---

### Task 1: Strengthen `_TAILOR_INSTRUCTIONS` and lock it with tests

**Files:**
- Modify: `callback/server.py:202-223` (`_TAILOR_INSTRUCTIONS`)
- Modify: `tests/test_server.py:703-774` (`test_submit_keywords_tailor_instructions_include_project_guidance`)

**Interfaces:**
- Consumes: existing `submit_keywords` → `data.tailor_instructions` envelope field
- Produces: `_TAILOR_INSTRUCTIONS` string that includes explicit keyword-mapping (not stuffing) guidance; project-edit anti-invention rules remain

- [ ] **Step 1: Write the failing test assertions**

In `test_submit_keywords_tailor_instructions_include_project_guidance`, extend the `actual` / `expected` dicts with these keys (keep all existing keys):

```python
        "mentions_keyword_mapping": "Keyword mapping, not stuffing" in instructions,
        "mentions_problems_first": "key_responsibilities" in instructions
        and "problems" in instructions,
        "prefers_fewer_strong": "fewer strong" in instructions,
        "leave_unsupported_uncovered": "leave it uncovered" in instructions,
```

And in `expected`:

```python
        "mentions_keyword_mapping": True,
        "mentions_problems_first": True,
        "prefers_fewer_strong": True,
        "leave_unsupported_uncovered": True,
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest tests/test_server.py::test_submit_keywords_tailor_instructions_include_project_guidance -v`

Expected: FAIL — new keys False in `actual` vs True in `expected`.

- [ ] **Step 3: Write minimal implementation**

Replace `_TAILOR_INSTRUCTIONS` in `callback/server.py` with:

```python
_TAILOR_INSTRUCTIONS = (
    "V4 voice constraints:\n"
    "- Bullets: past-tense action verb + mechanism (HOW) + metric from wiki. "
    "Banned verbs: spearheaded, orchestrated, championed, leveraged, utilized, streamlined.\n"
    "- Summary: ≤3 sentences, ≥1 quantified anchor. "
    "Banned: passionate, driven, results-oriented, proven track record.\n"
    "- Context line per role: <Role> · <Domain/Team> · <Scale signal> · <Stack>"
    " — factual only, no adjectives.\n"
    "- Skills: every keyword added to skills MUST appear in ≥1 dated experience bullet.\n"
    "- Keyword mapping, not stuffing: treat key_responsibilities (pass 2) as the "
    "employer's problems to solve first. Map only keywords that are truthfully backed "
    "by dated experience, project evidence, or wiki stories into real bullets that show "
    "how you solved similar problems. Prefer fewer strong, evidenced keywords over "
    "maximum coverage. If a keyword has no real experience behind it, leave it "
    "uncovered — do not invent facts, do not add keyword-only text, and do not pile "
    "synonyms into Skills.\n"
    "- Projects: use existing project descriptions or bullets when a missing required or "
    "preferred keyword is truthfully supported by project evidence rather than dated "
    "experience evidence. Project edits MUST be grounded in the source resume or "
    "profile wiki and MUST NOT invent project facts, metrics, scope, users, dates, "
    "employer context, or keyword-only text. Project evidence does not satisfy Skills "
    "coverage unless the keyword also appears in a dated experience bullet. When "
    "project_candidates are present, compare them against the visible resume project "
    "and prefer up to two visible projects when both projects improve JD keyword "
    "match or theme. Remove or shorten low-score, off-theme visible bullets before "
    "adding a second project. If two projects are already visible, replace the "
    "weakest visible project only when the candidate better fits the JD keywords "
    "or theme."
)
```

- [ ] **Step 4: Run test to verify it passes**

Run: `uv run pytest tests/test_server.py::test_submit_keywords_tailor_instructions_include_project_guidance -v`

Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add callback/server.py tests/test_server.py
git commit -m "$(cat <<'EOF'
feat: spell out keyword mapping (not stuffing) in tailor handoff

Issue #146 triage: strengthen host instructions without changing KeywordMatch.
EOF
)"
```

---

### Task 2: Problems-first language in post-pass-2 `host_task`

**Files:**
- Modify: `callback/server.py:911-943` (`_submit_keywords_workflow` tailor tasks)
- Modify: `tests/test_server.py:2276-2314` (`test_submit_responsibilities_replaces_trims_and_keeps_tailor_pending`)

**Interfaces:**
- Consumes: `_submit_keywords_workflow(..., pass_2_pending=False)` after `submit_responsibilities`
- Produces: `workflow.host_task` that tells the host to use `key_responsibilities` as employer problems first, map only evidenced keywords, leave unsupported gaps uncovered

- [ ] **Step 1: Write the failing test assertions**

In `test_submit_responsibilities_replaces_trims_and_keeps_tailor_pending`, extend `actual` / expected with:

```python
        "host_task_mentions_problems_first": (
            "key_responsibilities" in result["workflow"]["host_task"]
            and "problems" in result["workflow"]["host_task"]
        ),
        "host_task_leave_unsupported": "unsupported" in result["workflow"]["host_task"],
```

And in the expected dict:

```python
        "host_task_mentions_problems_first": True,
        "host_task_leave_unsupported": True,
```

Keep every existing assertion, including `"host_task_mentions_submit_keywords_reply": True`.

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest tests/test_server.py::test_submit_responsibilities_replaces_trims_and_keeps_tailor_pending -v`

Expected: FAIL — new host_task keys False.

- [ ] **Step 3: Write minimal implementation**

In `_submit_keywords_workflow`, replace `pass_2_tailor_task` only (leave the pass-2-pending `tailor_task` and `_PASS_2_TASK` unchanged except as needed for consistency):

```python
    pass_2_tailor_task = (
        "Use data.sections, data.score_gap, data.wiki_index, and "
        "data.tailor_instructions from the submit_keywords reply, plus the keywords "
        "returned here. Treat key_responsibilities as the employer's problems to solve "
        "first; map only keywords backed by dated experience, project evidence, or wiki "
        "stories; leave unsupported gaps uncovered — do not invent facts or keyword-stuff. "
        "Choose relevant wiki pages and prepare honest SectionMap edits. "
        "If the index already contains enough evidence, submit_tailor is also valid."
    )
```

Also update the still-pending `tailor_task` (used when pass 2 is still next) so the same mapping rule is visible before pass 2 completes — hosts may skip pass 2:

```python
    tailor_task = (
        "Use data.sections, data.score_gap, data.wiki_index, and "
        "data.tailor_instructions to choose relevant wiki pages and prepare "
        "honest SectionMap edits. Map keywords to evidenced experience that "
        "addresses the employer's problems; leave unsupported gaps uncovered. "
        "If the index already contains enough evidence, submit_tailor is also valid."
    )
```

If you change `tailor_task`, also extend `test_submit_keywords_tailor_instructions_include_project_guidance` (or the host_task checks in that test) so `"problems" in result["workflow"]["host_task"]` is True when pass 2 is pending. Add:

```python
        "host_task_mentions_problems": "problems" in result["workflow"]["host_task"],
```

expected `True`. Keep `"host_task_mentions_sections": True`.

- [ ] **Step 4: Run tests to verify they pass**

Run:

```bash
uv run pytest \
  tests/test_server.py::test_submit_keywords_tailor_instructions_include_project_guidance \
  tests/test_server.py::test_submit_responsibilities_replaces_trims_and_keeps_tailor_pending \
  -v
```

Expected: PASS for both.

- [ ] **Step 5: Commit**

```bash
git add callback/server.py tests/test_server.py
git commit -m "$(cat <<'EOF'
feat: problems-first tailor host_task after pass 2

Guide hosts to treat key_responsibilities as employer problems and leave
unsupported keyword gaps uncovered (#146).
EOF
)"
```

---

### Task 3: Align skill + eval tailor prompt + CHANGELOG

**Files:**
- Modify: `skills/tailor-resume/SKILL.md:38-44` (Tailoring Rules)
- Modify: `evals/runner.py:179-183` (extra bullets after `_TAILOR_INSTRUCTIONS`)
- Modify: `CHANGELOG.md` (Unreleased)

**Interfaces:**
- Consumes: `_TAILOR_INSTRUCTIONS` (already embedded in `tailor_prompt`)
- Produces: skill + runner copy that restates mapping-not-stuffing without contradicting server handoff

- [ ] **Step 1: Write a failing skill/runner content check (lightweight)**

Add to `tests/test_server.py` (or a small new test in the same file):

```python
def test_tailor_skill_and_eval_prompt_forbid_keyword_stuffing():
    from pathlib import Path

    from callback.server import _TAILOR_INSTRUCTIONS
    from evals.runner import tailor_prompt
    from evals.tailor_checks import TailorCase

    skill = Path("skills/tailor-resume/SKILL.md").read_text()
    assert "Keyword mapping, not stuffing" in _TAILOR_INSTRUCTIONS
    assert "Map keywords to real experience" in skill or "keyword mapping" in skill.lower()
    assert "Do not keyword-stuff" in skill or "do not keyword-stuff" in skill.lower()
    # runner still embeds server instructions; stuffing ban must remain in prompt extras
    case = TailorCase(
        name="probe",
        sections={"summary": "x", "skills": {"flat": [], "categorized": {}},
                  "experience": [], "projects": [], "education": [],
                  "contact": {}, "certifications": [], "awards": []},
        keywords={"required": ["Python"], "preferred": [], "required_any": [],
                  "preferred_any": []},
        wiki_pages={},
        constraints={},
    )
    prompt = tailor_prompt(case)
    assert "Keyword mapping, not stuffing" in prompt
    assert "Do not keyword-stuff" in prompt or "keyword-stuff" in prompt
```

If `TailorCase` construction differs from the fields above, open `evals/tailor_checks.py` and match the real dataclass / factory used by existing tests (e.g. load a committed case under `evals/tailor/`). Prefer:

```python
def test_tailor_skill_and_eval_prompt_forbid_keyword_stuffing():
    from pathlib import Path

    from callback.server import _TAILOR_INSTRUCTIONS
    from evals.runner import tailor_prompt
    from evals.cases import load_tailor_case  # use whatever loader existing evals tests use

    skill = Path("skills/tailor-resume/SKILL.md").read_text()
    assert "Keyword mapping, not stuffing" in _TAILOR_INSTRUCTIONS
    assert "map keywords to real experience" in skill.lower() or "keyword mapping" in skill.lower()
    case = load_tailor_case("jane-doe-redis")  # replace with a real committed case name
    prompt = tailor_prompt(case)
    assert "Keyword mapping, not stuffing" in prompt
    assert "keyword-stuff" in prompt
```

Discover the real case loader and case name with:

```bash
uv run pytest evals/test_tailor_checks.py -q --collect-only 2>/dev/null | head
rg -n "TailorCase|load_.*tailor" evals/ -g '*.py' | head -40
```

Use the real APIs; do not invent loaders.

- [ ] **Step 2: Run test to verify it fails on skill (and possibly runner extras)**

Run: `uv run pytest tests/test_server.py::test_tailor_skill_and_eval_prompt_forbid_keyword_stuffing -v`

Expected: FAIL until skill (and any missing runner line) is updated. `_TAILOR_INSTRUCTIONS` should already pass from Task 1.

- [ ] **Step 3: Update skill, runner extras, and CHANGELOG**

Replace the Tailoring Rules list in `skills/tailor-resume/SKILL.md` with:

```markdown
## Tailoring Rules

- Keyword mapping, not stuffing: use `key_responsibilities` (pass 2) as the employer's problems first. Map keywords to real experience that solves those problems.
- Add a keyword only when it is supported by dated experience or clear project evidence.
- Rewrite bullets only when the mechanism and impact are supported by the resume or fetched wiki stories.
- If no real experience backs a keyword, leave it uncovered — delete the suggestion. Do not keyword-stuff skills.
- Do not use banned filler language: spearheaded, orchestrated, championed, leveraged, utilized, streamlined, passionate, driven, results-oriented, proven track record.
- Prefer fewer strong edits over many weak edits.
```

In `evals/runner.py`, replace the three extra bullets after `_TAILOR_INSTRUCTIONS` with:

```python
        f"{_TAILOR_INSTRUCTIONS}\n"
        "- Keyword mapping, not stuffing: use key_responsibilities as the employer's "
        "problems first. Map only evidenced keywords into real bullets.\n"
        "- Add a keyword only when it is supported by dated experience or clear project evidence.\n"
        "- Rewrite bullets only when the mechanism and impact are supported by the resume or the "
        "wiki pages below.\n"
        "- If no real experience backs a keyword, leave it uncovered. Do not keyword-stuff "
        "skills. Prefer fewer strong edits over many weak edits.\n\n"
```

Under `CHANGELOG.md` `## Unreleased`, add:

```markdown
- Tailor handoff: explicit keyword-mapping (not stuffing) guidance — problems first via
  `key_responsibilities`, map only evidenced keywords, leave unsupported gaps uncovered.
  KeywordMatch scoring unchanged (#146).
```

- [ ] **Step 4: Run tests to verify they pass**

Run:

```bash
uv run pytest \
  tests/test_server.py::test_submit_keywords_tailor_instructions_include_project_guidance \
  tests/test_server.py::test_submit_responsibilities_replaces_trims_and_keeps_tailor_pending \
  tests/test_server.py::test_tailor_skill_and_eval_prompt_forbid_keyword_stuffing \
  -v
```

Expected: PASS for all three.

Also confirm scorer untouched:

```bash
git diff main -- callback/scorer.py
```

Expected: empty output (no scorer changes on this branch vs the branch base).

- [ ] **Step 5: Commit**

```bash
git add skills/tailor-resume/SKILL.md evals/runner.py CHANGELOG.md tests/test_server.py
git commit -m "$(cat <<'EOF'
docs: align skill and eval tailor prompts with mapping handoff

Keep host-facing copy consistent with #146; scoring unchanged.
EOF
)"
```

---

## Self-Review

1. **Spec coverage:** Issue #146 triage accept (strengthen tailor/pass-2 handoff, keep anti-stuffing explicit) → Tasks 1–3. Reject (non-linear KeywordMatch, score pass-2) → Global Constraints + Task 3 scorer diff check.
2. **Placeholder scan:** No TBD/TODO steps; test code and replacement strings are concrete. Task 3 notes discovering the real TailorCase loader instead of inventing one.
3. **Type consistency:** Strings only; no new functions/types. Envelope fields `data.tailor_instructions` and `workflow.host_task` unchanged in shape.
