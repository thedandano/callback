# Design: OR-group scoring + atomic keyword extraction (+ go-apply removal)

Date: 2026-07-09
Repo: `~/workplace/callback` (branch off `main`)
Guided by: ponytail (full) — shortest working diff, deletion over addition.

## Problem

Keyword matching is literal (`scorer._compile_keyword_pattern` `re.escape`s the
keyword, plural-tolerates only the last token, word-boundary anchored). Two
consequences hurt real scores:

1. **Sentence-style requirement bullets** get extracted as one giant `required`
   keyword (e.g. "Java or some other object oriented programming language"),
   which can never match a resume. The atomic term ("Java") would. This also
   poisons every downstream consumer of `req_unmatched`: `score_gap.required_missing`,
   orphan detection, `create_story.primary_skill`, project ranking.
2. **Disjunctive requirements** ("one or more of A, B, C") have no primitive.
   The only current handling is a lossy workaround (dump alternatives into
   `preferred`) that (a) can leave `required=[]` → `JDDataError` /
   `_run_score` ValueError, and (b) silently re-splits keyword weight 70/30
   when it creates a `preferred` bucket that was empty.

## Non-goals (YAGNI)

- No regex/alternation syntax inside keyword strings.
- No synonym/abbreviation expansion in matching (honest-signal rule stays).
- Project ranking (`_project_score`) and bullet/project-swap trimming
  (`_trim_candidates`) are **not** taught about `required_any`; they keep scoring
  flat `required`/`preferred` only. Under the old preferred-workaround, group
  members sat in `preferred` and *did* count here; after this change they count
  nowhere in project/trim ranking. Accepted.
  `# ponytail: project/trim ranking ignores required_any groups; revisit only if selection quality visibly drops.`
- Unmatched `required_any` group members never become orphans, so they never
  trigger the `create_story` nudge. Accepted — a group is a disjunction, not a
  single missing skill to write a story for.

## Part A — atomic extraction (prompt-only)

File: `callback/jd_data.py` → `EXTRACTION_PROTOCOL`.

Add one rule + fold into the existing example set:

- **Extract atomic terms, never whole sentences/clauses.** A requirement bullet
  is often a full sentence; emit the individual skills/tools/tech/methodologies/
  credentials named inside it. Never emit a sentence or clause as a keyword (the
  scorer matches literally). Keep each atomic term verbatim (`k8s` stays `k8s`;
  no synonym swap).
- **Inline "X or some other Y" / "X or equivalent":** only `X` is a matchable
  named term, so extract `X` as a normal atomic `required` term (e.g. "Java or
  some other OOP language" → `Java`). Never keep the "or some other …" clause as
  text. A one-member group would be scoring-identical, so don't make one.
  `required_any` (Part B) is only for when **two or more concrete alternatives**
  are named (e.g. "Java, C++, or Go" → `[["Java","C++","Go"]]`).

No code path change. Tests assert the guidance strings are present (same style
as existing `assert "..." in EXTRACTION_PROTOCOL`).

## Part B — `required_any` OR-group primitive

The correct model: a group scores as **one required unit, matched iff ANY member
matches**, at full required weight. Structurally removes the empty-`required`
crash and the weight re-split.

### Schema — `callback/jd_data.py`

- Add field: `required_any: list[list[str]] = field(default_factory=list)`.
- Validate in `__post_init__`: each group is a non-empty list of non-empty
  strings (reuse the `_clean_keywords` string-cleaning; add a small
  `_clean_groups` helper). Drop empty groups; strip blank members.
- Change the empty guard:
  `if not self.required and not self.required_any: raise JDDataError("invalid_jd", "required or required_any must be non-empty")`.
- `EXTRACTION_PROTOCOL`: rewrite rule 2 — enumerable disjunctions
  ("one or more of" / "any of" / interchangeable alternatives) go to
  `required_any` as a group; `preferred` reverts to genuine nice-to-haves.
  Add `required_any` to the JSON schema line + a worked example.

### Plumbing — `callback/apply_nodes.py:_run_score` (3 hops, not just the guard)

The keywords dict is unpacked **here**, not in `score()` (which takes flat
lists). All three hops live in `_run_score` and cover both `score_initial` and
`score_final`:

1. **Guard (~line 89):** change `if not keywords or not keywords.get("required")`
   to also accept a non-empty `required_any`.
2. **Call site (~lines 91-99):** pass `keywords.get("required_any", [])` into
   `scorer.score(...)`.
3. **Return dict (~lines 100-122):** add
   `"req_group_unmatched": r.keywords.req_group_unmatched`. **Without this hop,
   `server.py:~896` `score.get("req_group_unmatched", [])` is always `[]` and
   `required_missing_any` ships dead — a silent failure.** `score_final` then
   carries the field into the `submit_tailor` report for free.

### Scorer — `callback/scorer.py`

- `KeywordResult`: add `req_group_unmatched: list[list[str]] = field(default_factory=list)`
  (groups where no member matched). Keep groups OUT of `req_unmatched`
  (that flat list feeds orphan detection, which regex-escapes each entry — a
  group label would break it).
- `_score_keywords(resume_text, required, preferred, required_any, cfg)`:
  - **Both** empty-branches must include `required_any`, they are separate:
    - early return (~line 246): `if not required and not preferred and not required_any: return KeywordResult(...), 0.0`.
    - reweight branch (~lines 251-254): `if not required and not required_any` → `req_w,pref_w = 0.0,1.0`.
  - denominator: `req_total = len(required) + len(required_any)`.
  - a group is matched iff any member's compiled pattern hits the resume.
  - `req_pct = (len(req_matched) + group_matched_count) / req_total if req_total else 0.0`
    (the `if req_total else 0.0` guards ZeroDivision — `score()` is a public pure
    function tests call directly, bypassing schema validation, so `required=[]`+
    `required_any=[]`+non-empty `preferred` is reachable).
  - **No double-count:** a matched group's member does **not** go into
    `req_matched`; `group_matched_count` is counted separately. Matched groups are
    not reported anywhere (nothing consumes them) — only `req_group_unmatched` is.
  - populate `req_group_unmatched` (groups where no member matched).
- `scorer.score()` (scorer.py:149) gains a defaulted `required_any: list[list[str]] = []`
  param and forwards it to `_score_keywords` (single call site, scorer.py:169).

### Reporting — `callback/server.py`

- `submit_keywords` `score_gap`: add `"required_missing_any": score.get("req_group_unmatched", [])`
  so the tailoring loop can cover an unmet group. Orphan detection stays on the
  flat `req_unmatched` only (unchanged).

### Backward compat

Default `[]` keeps all existing payloads valid. `dataclass_wizard` silently
drops unknown keys, so a host emitting `required_any` at an **old** server gets
silent degradation → **call this out in CHANGELOG** (no-silent-failure policy).

## Part C — remove deprecated go-apply

go-apply is deprecated and fully superseded; `bridge.py` is wired into nothing
at runtime (only its own tests import it).

**Delete:** `callback/bridge.py`, `tests/test_bridge.py`, and the
`restore_bridge_module` autouse fixture in `tests/conftest.py` (~lines 24-44) —
leave the adjacent module-pop lines (~20-21) alone. (`.env.example` has **no**
`GO_APPLY_BIN` line — only `LOG_LEVEL`/`CALLBACK_TEST_STUB`; nothing to delete there.)

**Edit (live docs/refs):** drop the "matching go-apply" line in
`jd_data.py:~42`; rename `tests/test_jd_data.py::test_full_jddata_preserves_go_apply_fields`;
remove the `bridge.py`/`GO_APPLY_BIN` "kept for tests" rows and go-apply-parity
lines from `AGENTS.md`, `CLAUDE.md`, `BRIEF.md`.

**Keep (history):** `CHANGELOG.md`, `DECISIONS.md`, `EPICS.md` — historical
records, not live wiring.

## Testing (new, minimal)

- `tests/test_jd_data.py`: `required_any` parse/validate (groups cleaned, blanks
  dropped); empty `required` + non-empty `required_any` is **valid**; empty both
  **raises**; atomic-extraction + `required_any` guidance strings present in
  `EXTRACTION_PROTOCOL`.
- `tests/test_scorer.py` (or existing scorer test file): group matches on any
  member; group counts at full required weight (denominator math); a fully
  unmatched group appears in `req_group_unmatched`; empty-`required`-only-groups
  path scores.
- Full suite green after go-apply deletion (no import errors, conftest fixture
  removal clean).

## Reviewer regression checklist

The reviewer must confirm each — these guard the exact things this change can break:

- [ ] **Backward compat:** a payload with `required_any` absent/`[]` scores
      byte-identically to before (flat `required`/`preferred` path untouched).
- [ ] **No weight re-split introduced:** with `required` non-empty and
      `preferred` empty, `req_w/pref_w` stays `1.0/0.0` (the workaround no longer
      manufactures spurious `preferred` buckets).
- [ ] **Empty guards:** `required=[]` **and** `required_any=[]` still raises
      (both in `JDData.__post_init__` and `_run_score`); `required=[]` with a
      non-empty `required_any` is now accepted end-to-end.
- [ ] **Group semantics:** a group matches iff ≥1 member matches; a matched
      group contributes exactly one full required unit (same weight as a scalar
      required keyword); denominator = `len(required)+len(required_any)`.
- [ ] **Orphan detection / create_story untouched:** `req_unmatched` (flat)
      never contains group members or group labels; `_detect_orphaned_required`
      and `create_story.primary_skill` still receive only atomic strings.
- [ ] **Reporting:** unmatched groups surface via `score_gap.required_missing_any`
      (list of groups), not jammed into `required_missing`.
- [ ] **`required_missing_any` alive end-to-end:** an integration call to
      `submit_keywords` with an unmatched group returns a **non-empty**
      `required_missing_any` (the scorer unit test alone won't catch the dead
      `_run_score` return-dict hop).
- [ ] **No double-count:** a matched group's member does not also appear in
      `req_matched`; `req_pct` numerator adds `group_matched_count` separately.
- [ ] **No ZeroDivision / early-return-to-zero:** `score()` with `required=[]` +
      non-empty `required_any` + non-empty `preferred` reweights 0.7/0.3 and does
      not divide by zero or short-circuit to 0.
- [ ] **`score_final` carries it:** the `submit_tailor` report includes
      `req_group_unmatched` (via the same `_run_score` return-dict hop).
- [ ] **Atomic extraction:** protocol forbids whole-sentence keywords and keeps
      verbatim terms; the second example demonstrates a sentence → atomic terms.
- [ ] **go-apply deletion:** `grep -rn "bridge\|GO_APPLY_BIN"` shows no live
      (non-history, non-deleted) references; full test suite passes; no dangling
      imports; `conftest.py` still valid for the remaining suite.
- [ ] **CHANGELOG** notes the old-server silent-drop of `required_any`.
- [ ] **Behavior check:** the Apple "Software Engineer - Universal Media"
      re-score moves up vs. the 45.99 (v2) baseline once its sentence bullets
      decompose and its disjunctive group is credited.

## Rollout

- Branch off `main`; one PR.
- CHANGELOG entry (feat: `required_any` OR-groups + atomic extraction; chore:
  remove deprecated go-apply bridge) — release-please manages versioning.
