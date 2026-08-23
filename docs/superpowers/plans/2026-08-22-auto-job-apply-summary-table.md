# auto-job-apply Summary Table Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Replace the four separate role tables in the `/auto-job-apply` final summary with one score-sorted table that shows the per-dimension score breakdown, coverage percentages, before→after score, and a short recommendation.

**Architecture:** This is a prompt/instruction change to a single Markdown skill file. No Python changes. The callback MCP already returns every number the new table needs — `submit_tailor`'s `data.report.before` / `data.report.after` carry all five scoring dimensions plus required/preferred coverage. The current template just never surfaced them. The work is: widen the role-agent return contract so the parent receives the per-dimension block, then rewrite the Final Summary section around one merged table.

**Tech Stack:** Markdown only (`skills/auto-job-apply/SKILL.md`). No code, no tests, no dependencies.

**Spec:** No separate spec document. The output format was locked interactively during this planning session on 2026-08-22 — the exact chosen table shape is reproduced verbatim in Task 2.

## Context

**Why:** The `/auto-job-apply` run summary is hard to read. It splits roles across four tables (`Scored Roles`, `Review Queue`, `Referral Leads`, `Skipped Or Source-Limited`), so comparing two roles means scanning two tables. It also shows only raw before/after totals — a role scoring 72 and a role scoring 84 look similar with no way to see *which dimension* differs. The scorer is 55/15/10/10/10 across five dimensions and computes required/preferred keyword coverage, but none of that reaches the user.

**Outcome:** One `## Roles` table, sorted by final score descending, with the breakdown visible per row. Detail that used to inflate the tables (URL, salary, location, artifact paths, req ID, level mapping) moves to a short block below the table, shown only for roles that need action.

## Global Constraints

- Only `skills/auto-job-apply/SKILL.md` changes. Do not touch `references/record-schema.md`, sibling skills, or any Python.
- The CSV `Status` column keeps the full vocabulary from `references/record-schema.md` verbatim. Only the summary table abbreviates. Never write a short `Rec` label into the CSV.
- The 70-point gate is unchanged. This is presentation only — no scoring, gating, or application logic changes.
- Table separator style: space-padded `---` for text, `---:` for right-aligned numbers. This matches the file's existing tables.
- Do not invent data. Every number in the table maps to a named field in `data.report`.

---

### Task 1: Widen the callback role agent return contract

The parent builds the Roles table from what role agents hand back. Today the contract (line 142) asks only for "before score, after score" — the parent cannot fill the breakdown columns from that. Fix the contract first, or Task 2 produces a table the run cannot populate.

**Files:**
- Modify: `skills/auto-job-apply/SKILL.md:142` (Workflow step 12)

- [ ] **Step 1: Replace Workflow step 12**

Find this line (line 142):

```
12. Each callback role agent returns a standardized Markdown result row/table with source URL, company, title, salary, location, before score, after score, status recommendation, artifact links, strongest overlaps, missing keyword clusters, seniority/source risks, and whether actual edits were applied or this was no-coverage.
```

Replace with:

```
12. Each callback role agent returns a standardized Markdown result row/table with source URL, company, title, salary, location/work type, requisition ID and level mapping when known, artifact paths, status recommendation, strongest overlaps, missing keyword clusters, seniority/source risks, and whether actual edits were applied or this was no-coverage. It must also return the complete `data.report.before` and `data.report.after` blocks from `submit_tailor` verbatim — every field of `total`, `keyword_match`, `required_coverage`, `preferred_coverage`, `experience_fit`, `impact_evidence`, `ats_format`, `readability`, plus `experience_evaluated`. The parent needs the full per-dimension block to build the Roles table; a bare before/after total is not enough.
```

- [ ] **Step 2: Verify**

Run: `grep -n "data.report.before" skills/auto-job-apply/SKILL.md`
Expected: one hit, on the rewritten step 12.

---

### Task 2: Rewrite the Final Summary section

**Files:**
- Modify: `skills/auto-job-apply/SKILL.md:176-227` (the entire `## Final Summary` section through the end of the file)

- [ ] **Step 1: Replace everything from `## Final Summary` (line 176) to end of file**

Delete lines 176-227 and write in their place:

````markdown
## Final Summary

Use Markdown as the standardized output format. One table carries every role. Use short prose only where a table cannot say it. If the local dashboard has been generated, include its path as a secondary artifact, but the Markdown summary remains the required automation output.

Emit exactly these blocks, in this order:

1. `Run title: ...`
2. `## Stats`
3. `## Discovery Sources`
4. `## Roles` — every role that entered the queue, one row each, sorted by final score highest-first. Rows that never reached callback (`No source`, `Blocked`, `Duplicate`, `Recruiter`, `Not scored`) sort last, alphabetically by company.
5. `### Details - action needed` — only for rows whose `Rec` is `Review`, `Referral`, or `Applied`. Skip the heading entirely when no row qualifies.
6. One closing line. If nothing was applied, say that plainly.

Do not emit separate `Scored Roles`, `Review Queue`, `Referral Leads`, or `Skipped` tables. Those are rows in `## Roles`, distinguished by the `Rec` column.

### Roles table column rules

Every number comes from `submit_tailor`'s `data.report`. Do not compute or estimate any of them.

- `KW /55`: `after.keyword_match`, rounded to a whole number.
- `Req%` / `Pref%`: `after.required_coverage` / `after.preferred_coverage`, whole percent. Write `—` when `preferred_coverage` is null (the JD listed no preferred keywords).
- `Rest`: `Exp {n} · Imp {n} · ATS {n} · Rd {n}` from `after.experience_fit`, `after.impact_evidence`, `after.ats_format`, `after.readability`, whole numbers. Write `Exp n/a` when `experience_evaluated` is false.
- `Score`: `{before} → {after}` from `before.total` and `after.total`, whole numbers. Equal values (e.g. `62 → 62`) mean no-coverage or no lift — say which in `Notes`.
- Rows that never reached callback get `—` in every score cell.
- `Rec`: the short label from the table below.
- `Notes`: ONE clause, 12 words maximum — the mismatch summary, blocker, or risk in plain words. The full rationale goes in the CSV `Notes` column, not here.

### Recommendation labels

`Rec` is a display label for the summary table only. The record CSV `Status` column keeps the full vocabulary from [record-schema.md](references/record-schema.md) — never abbreviate there.

| Rec | CSV `Status` |
| --- | --- |
| `Review` | `Needs review - not applied` |
| `Referral` | `Referral lead - ask friend` |
| `Skip` | `Scored - below threshold` |
| `Applied` | `Applied` or `Already applied - confirmation recorded` |
| `Rejected` | `Rejected` |
| `No source` | `Needs source - manual lookup` |
| `Not scored` | `Needs callback score - not applied` |
| `Blocked` | `Skipped - hard blocker`, `Skipped - not fit`, or `Closed - not scored` |
| `Rescored` | `Rescored - not applied` |
| `Duplicate` | `Duplicate alert - already scored` |
| `Recruiter` | `Recruiter follow-up` |

### Details block

One entry per action-needed role, in the same order as the table. Three lines each:

1. `**{Company} · {Title} · {final score} · {Rec}**`
2. `{salary} · {location/work type} · {source URL}` — plus ` · req {id}` and ` · {level mapping}` when known.
3. Artifact paths, then the next action if there is one.

### Final Markdown Template

```markdown
Run title: Auto Job Apply - YYYY-MM-DD - HH PT

## Stats
| Jobs found | Curated | Scored | Applied | Max score | Mean score | Min score | Status emails | Source-manual leads | Referral leads |
| ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: |
| 0 | 0 | 0 | 0 | N/A | N/A | N/A | 0 | 0 | 0 |

## Discovery Sources
| Source | Kind | Leads returned | Full sources | Needs manual source | Notes |
| --- | --- | ---: | ---: | ---: | --- |
| (one row per enabled scan_source) |  | 0 | 0 | 0 |  |

## Roles
| Company | Title | KW /55 | Req% | Pref% | Rest | Score | Rec | Notes |
| --- | --- | ---: | ---: | ---: | --- | ---: | --- | --- |
| Netflix | Sr SWE, LLM Eval | 41 | 78% | 60% | Exp 15 · Imp 8 · ATS 10 · Rd 10 | 71 → 84 | Review | Comp not listed |
| Stripe | Backend Eng L3 | 33 | 61% | 40% | Exp 15 · Imp 6 · ATS 10 · Rd 8 | 66 → 72 | Review | Kafka gap |
| Meta | E5 AI Infra | 30 | 55% | 33% | Exp 15 · Imp 6 · ATS 10 · Rd 8 | 61 → 68 | Referral | Below gate, ask friend first |
| Datadog | AI Platform Eng | 26 | 47% | — | Exp n/a · Imp 8 · ATS 10 · Rd 10 | 62 → 62 | Skip | No wiki story covered gaps |
| Anduril | Sr SWE, Autonomy | — | — | — | — | — | Blocked | Active clearance required |

### Details - action needed
**Netflix · Sr SWE, LLM Eval · 84 · Review**
$220-310k · Remote-from-SD · https://jobs.netflix.com/jobs/1234567
`.../applications/2026-08-22/netflix-llm-eval/resume.pdf`

**Meta · E5 AI Infra · 68 · Referral**
$240-330k · Menlo Park hybrid · https://metacareers.com/jobs/7654321 · req 7654321 · E5 maps to target band
`.../applications/2026-08-22/meta-ai-infra/resume.pdf` · ask friend for referral before applying

Nothing applied this run.
```
````

- [ ] **Step 2: Verify the old tables are gone**

Run: `grep -n "## Scored Roles\|## Review Queue\|## Referral Leads\|## Skipped Or Source-Limited" skills/auto-job-apply/SKILL.md`
Expected: no output.

- [ ] **Step 3: Verify the new table is present and well-formed**

Run: `grep -n "| Company | Title | KW /55 | Req% | Pref% | Rest | Score | Rec | Notes |" skills/auto-job-apply/SKILL.md`
Expected: exactly one hit.

Then eyeball the rendered file: every pipe table must have the same number of `|` in its header row, separator row, and each body row. The `Roles` table is 9 columns, so each row has 10 pipes.

---

### Task 3: Point the surrounding workflow steps at the new format

Two workflow steps still describe output shaped like the old tables. Left alone they contradict the new Final Summary.

**Files:**
- Modify: `skills/auto-job-apply/SKILL.md:143` (Workflow step 13)
- Modify: `skills/auto-job-apply/SKILL.md:145` (Workflow step 15)
- Modify: `skills/auto-job-apply/SKILL.md:4` (frontmatter `version`)

- [ ] **Step 1: Append a pointer to Workflow step 13**

Find the end of line 143:

```
13. Parent reconciles callback agent results, writes a quick mismatch summary for every scored role in simple language, and records why each score landed where it did. For scores under 70, this explanation is required before moving on.
```

Append this sentence to it:

```
 The full explanation goes in the CSV `Notes` column; the Roles table `Notes` cell gets a single clause of 12 words or fewer.
```

- [ ] **Step 2: Append a pointer to Workflow step 15**

Find the end of line 145 (`...preserve the referral-first note and referral outreach action.`) and append:

```
 Surface these as `Review` and `Referral` rows in the Roles table, with salary, source URL, and artifact paths in the details block beneath it.
```

- [ ] **Step 3: Bump the skill version**

In the frontmatter, change `version: 1.4` to `version: 1.5`.

Note: this is the skill-internal version. Leave `.claude-plugin/plugin.json` alone — release-please owns that.

- [ ] **Step 4: Commit**

```bash
git add skills/auto-job-apply/SKILL.md
git commit -m "feat(skill): merge auto-job-apply role tables into one scored summary table"
```

---

## Verification

No automated tests cover this file — `tests/test_plugin_install.py` does not reference it, and there is no skill-content test. Verify by hand:

1. **Static check.** `grep -c '|' ` each row of the new Roles table; header, separator, and every example row must match. Run `uv run pytest -q` once to confirm nothing unrelated broke (expect the existing suite to pass untouched).
2. **Contradiction sweep.** `grep -n "Review Queue\|Referral Leads\|Scored Roles" skills/auto-job-apply/SKILL.md` — any surviving hit is prose still describing the old layout. Fix it.
3. **Live dry run.** In a fresh session, run `/auto-job-apply` scoped to a small window (one enabled source, `recency_days: 1`). Confirm the final response has exactly one `## Roles` table, sorted highest score first, with populated `KW /55`, `Req%`, `Pref%`, `Rest`, and `{before} → {after}` cells for every scored role. Confirm the details block appears only for `Review` / `Referral` / `Applied` rows.
4. **Null-path check.** In that run, confirm at least one row exercises each edge: a JD with no preferred keywords renders `Pref%` as `—`; a role where `experience_evaluated` is false renders `Exp n/a`; a blocked/no-source role renders `—` across all score cells.
5. **CSV integrity.** Open the record CSV afterward and confirm the `Status` column holds full vocabulary strings (`Needs review - not applied`), not the short `Rec` labels.

## Out of scope

- `skills/apply-to-job/SKILL.md` has its own output spec (lines 47-56) describing the same four-table layout. It was not part of this request. Worth syncing in a follow-up so the two skills do not disagree.
- `.clone_skill_dir/` is a stale gitignored snapshot of this skill. Leave it; it is not on the load path.
