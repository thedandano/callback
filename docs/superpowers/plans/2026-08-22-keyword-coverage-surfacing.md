# Show a keyword match percentage

**Date:** 2026-08-22
**Size:** Small
**Status:** Waiting for approval

## The problem

Right now callback gives you one number you can actually use: the overall score
out of 100, where 70 is a pass.

For keywords it shows `keyword_match: 41.2`. That's points out of a possible 55.
Nobody reads that and thinks "I'm hitting 75% of the keywords this job asked
for."

The percentage already gets calculated. `_score_keywords` works it out
(`callback/scorer.py:306-308`) and hands it back on a small results object
(`callback/scorer.py:128-137`). Then nothing uses it. The function that packages
up the score for everyone else, `_run_score`, doesn't copy it
(`callback/apply_nodes.py:102-126`), so it never reaches the reply the host gets
(`callback/server.py:896-901`) or the final report
(`callback/apply_nodes.py:658-674`).

So today callback tells you *which* keywords you're missing, but never *how much*
you're covering. And the final report can't show how much the tailoring pass
improved things.

## What we want to see

```
Resume score:        74 / 100
Required keywords:   91%   (10 of 11)
Preferred keywords:  67%
```

## What we're deliberately not doing

- **No pass mark for keywords.** We won't say "you need 90-95% coverage." Give
  people a keyword target and they'll pad the resume to hit it. That's the exact
  thing the project rules forbid ("Never keyword-stuff. Honest signal only.").
  The list of missing keywords is the goal. The percentage is just context.
- **No change to scoring.** The weights, the 70 pass mark, the overall number
  all stay exactly as they are. We're only showing something that's already
  being worked out.
- **No new settings.** `ScoringConfig` isn't touched.

## How it works

### The number itself

The scorer stores coverage as a decimal between 0 and 1. Turn it into a
percentage (0 to 100, one decimal place) at the point where `_run_score`
packages things up. That matches how every other number in that package is
already scaled. The scorer's own maths keeps the decimal — nothing below
`_run_score` changes.

Call the fields `required_coverage` and `preferred_coverage`.

### Counting "either/or" keywords

Some jobs accept alternatives — "Python or Go" counts as one requirement, not
two. The scorer already counts those as a single item
(`callback/scorer.py:306-308`). We reuse that count as-is, so the percentage
matches the score it came from. No second way of counting.

### When a job lists no required keywords

The scorer currently returns 0 in that case. Show nothing instead of 0%,
because "this job didn't list any required keywords" is not the same as "you
matched none of them". Callback already does this for years-of-experience: it
returns nothing rather than a zero when there's nothing to measure.

### The three edits

| # | File | What changes |
|---|------|--------------|
| 1 | `callback/apply_nodes.py:102` (`_run_score`) | Include the two new percentages when packaging the score |
| 2 | `callback/apply_nodes.py:570` (`_SCORE_DIMS`) | Add both names to this list |
| 3 | `callback/server.py:896` (`score_gap`) | Include both in the reply, next to the missing-keyword lists |

Why edit 2 matters: that list drives the final report's before / after /
improvement columns. Add the two names and coverage gets those columns for free,
without writing any new code.

One wrinkle worth naming: the list is called `_SCORE_DIMS`, meaning "the parts
of the score", and a percentage isn't really a part of the score. Slightly wrong
name. Doing it anyway, because both numbers already run 0 to 100, the
before/after code already copes with a missing value (it does that for
years-of-experience), and we get the whole comparison for nothing. If the name
starts to grate later, that's a rename, not a rethink.

## What this breaks

Five tests in `tests/test_scoring_engine.py` check the score package by
comparing the whole thing at once, key for key. Adding two keys makes all five
fail. That's the tests doing their job — this project deliberately compares
whole objects rather than picking out single values.

Also worth checking: `tests/test_score_roundtrip.py`, `tests/test_apply_e2e.py`,
`tests/test_submit_tailor.py`, `tests/test_apply_graph.py`, and
`tests/test_state.py` all mention `keyword_match` and may check the shape of the
report or the reply.

## Order of work

### Step 1 — get the percentage into the score

Edits 1 and 2. Fix the five broken tests.

New tests: a resume matching every keyword, a resume matching some, an
"either/or" pair counted once, and a job with no required keywords (should show
nothing, not 0%).

Finished when `_run_score` returns both percentages, the report shows before /
after / improvement for them, and these all pass:
`uv run pytest`, `uv run pyright`, `uv run ruff check`.

### Step 2 — get it into the reply the host sees

Edit 3. `submit_keywords` returns coverage next to the missing keywords. Update
the checks in `tests/test_server.py`.

Finished when a `submit_keywords` call comes back with
`score_gap.required_coverage`, the whole test suite passes, and
`scripts/smoke_apply.py` shows both numbers running end to end.

## Before the pull request

```bash
uv run pytest
uv run pyright
uv run ruff check
uv run python scripts/smoke_apply.py
```

All four have to pass. Both steps go in one pull request — the change is small
enough that splitting it would make it harder to read, not easier.

## How risky is this

Low. We're adding two fields to a reply, and this project already grows replies
by adding rather than replacing (see the `clarify-mcp-host-handoff` change:
"add fields rather than replacing"). Scoring behaviour doesn't change, so no
already-saved application gets a different score.
