# Per-Eval Score Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use `superpowers:executing-plans` to implement this plan task-by-task.

**Goal:** Show each eval's actual passed-check count against its passing target beside its status.

**Architecture:** Derive the score on `EvalRow`, the existing one-row-per-fixture result object. The table renders that value; checks remain the source of truth.

**Tech Stack:** Python 3.12, pytest.

**Spec:** Conversation request on 2026-09-28: print `actual/passing_target` for every eval result.

## Global Constraints

- Do not change pass/fail rules, fixtures, prompts, or model calls.
- Count only non-skipped checks toward the target.
- Preserve `PASS`, `FAIL`, and `SKIP` behavior.

## Review Focus

- All checks pass: score is `N/N`.
- One check fails: score counts only passed checks.
- Mixed executed and skipped checks: skipped checks do not increase the target.
- All checks skipped: score prints `—`.
- Short-circuit malformed output: its one failed validity check prints `0/1`.

### Task 1: Derive and Render the Eval Score

**Files:**

- Modify: `evals/runner.py`
- Modify: `evals/test_runner.py`

**Interfaces:**

- Produces: `EvalRow.score: str`, formatted as `actual/target` or `—`.
- Consumes: existing `Check.passed` and `Check.skipped` fields.

- [ ] Add focused tests for passing, failing, mixed-skip, all-skip, and malformed rows.
- [ ] Add the minimal `EvalRow.score` property and render it in `format_table`.
- [ ] Run `uv run pytest evals/test_runner.py -q` and `UV_CACHE_DIR=/private/tmp/callback-uv-cache uv run pytest -m "not local" evals/`.
- [ ] Commit and open a pull request.
