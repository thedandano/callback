---
name: tailor-resume
description: Tailors one resume for one job description using callback. Use when the user asks to "tailor my resume", "score this job", "run callback on this JD", "use callback for this job", "make a tailored resume", "apply callback to this posting", or provides one job URL or full job description for resume tailoring.
---

# Tailor Resume

## North Star

Use callback to produce one honest tailored resume that clears AI screening and survives a human skim — aiming to land an interview — for one validated job description.

## Scope

This is a one-job workflow. Do not scan Gmail, Google Jobs, FAANG careers, the job ledger, unemployment trackers, or application forms. Do not submit applications.

## MCP Flow

1. Call `load_jd` with exactly one source:
   - `jd_url` for a current full job page, or
   - `jd_raw_text` for pasted full JD text.
   - One resume is registered at a time; `onboard_user` replaces it.
2. Extract compact JDData from `data.jd_text` using `data.extraction_protocol`. For disjunctive "one or more of" / "any of" requirement groups, put the alternatives in a `required_any` group (or `preferred_any` when the group sits under a preferred section) — only one is needed, so a candidate who has any single one satisfies it and must not be penalized for lacking the others.
3. Call `submit_keywords(session_id, jd_json)`.
4. Follow `workflow.next_tool`:
   - `submit_responsibilities`: start a fresh subagent and give it only `data.responsibilities_protocol` and the `data.jd_text` from `load_jd`. Send the `key_responsibilities` list it returns to `submit_responsibilities(session_id, key_responsibilities)`, then follow the next `workflow.next_tool`. If you cannot start a subagent, skip this step.
   - `get_wiki_pages`: fetch relevant page IDs from `data.wiki_index`, then tailor with that evidence.
   - `submit_tailor`: tailor directly from visible resume evidence.
   - `onboard_user` or `create_story`: stop and explain what profile evidence is missing.
5. Call `submit_tailor(session_id, edits=[...])`, or use `no_coverage=True` only when no truthful supported edits exist. If `.callback/config.json` is present and sets `applications_dir`, pass `output_dir` as the absolute path of `applications_dir/<YYYY-MM-DD>/<company-role-slug>/` so the tailored PDF lands in the project folder instead of callback's hidden data directory.
6. Return `pdf_path`, `ledger_path`, before/after scores, accepted/rejected edits, uncovered skills, and a short mismatch summary.

## Failure Contract

- If any tool returns `"status": "error"`, the requested artifact or score **does not exist**. Report the error and stop. Never synthesize a substitute: no hand-scoring, no hand-rendering, no "text-based" fallbacks for `score_final`, no estimating missing numbers.
- Every number you report (scores, coverage, dimensions) must come from a tool response — cite the producing tool and `session_id`. A number without provenance is an invention, not a result.
- On `pipeline_error` with `"retriable": true` and `"host_action": "report_and_wait"`: you may retry the same tool call with the same `session_id`. You may not invent the missing output while you wait.

## Tailoring Rules

- Keyword mapping, not stuffing: use `key_responsibilities` (pass 2) as the employer's problems first. Map keywords to real experience that solves those problems.
- Add a keyword only when it is supported by dated experience or clear project evidence.
- Rewrite bullets only when the mechanism and impact are supported by the resume or fetched wiki stories.
- Bullet craft uses Google XYZ: Accomplished X (result), as measured by Y, by doing Z (how). Prefer this shape when polishing quantified bullets. Never invent or change numbers — Y must come from the resume, wiki, or stories.
- XYZ honesty guards:
  - Scope is not a result — “across 20+ sources” / “in six countries” alone must not stand in for X.
  - No duplicate metrics — do not credit the same figure to two different bullets.
  - Do not strengthen X past the evidence; context can demote a stronger-sounding claim.
  - Ambiguous bullets need a specific X (what broke, who was affected) before rewriting.
- If no real experience backs a keyword, leave it uncovered — delete the suggestion. Do not keyword-stuff skills.
- Facts first: polish wording without changing any facts. Keep only wording you could explain in an interview.
- Do not use banned filler language: spearheaded, orchestrated, championed, leveraged, utilized, streamlined, passionate, driven, cross-functional, results-oriented, results-driven, proven track record, operational excellence.
- Prefer fewer strong edits over many weak edits.
- When the JD asks for AI / LLM / Copilot / ChatGPT (or similar) skills, prefer evidenced AI outcomes in experience or project bullets (tool + problem + result, grounded in resume/wiki/stories) over only listing the tool name in Skills. Never invent AI work. Do not auto-reorder bullets solely to put an AI win first.

## Chat-supplied XYZ facts

If the user provides new truthful metrics or context in chat (chat-supplied facts not yet in the resume or wiki):

1. Confirm the fact list with the user before persisting.
2. Call `create_story` with: `primary_skill` (required label), `skills` (must include `primary_skill`), `story_type` (SBI), `job_title` (confirmed role), and SBI fields `situation` / `behavior` / `impact` — put the metric or verifiable outcome in `impact`. Omit `session_id` unless a profile tool reply set `next_action` to `create_story` (never pass an apply `session_id`).
3. Continue or re-run tailor so wiki evidence can ground Google XYZ bullets.
4. If the user declines, use the facts for this session only and say later runs will not see them.

Never invent numbers or context to fill XYZ.

## Output

Use a compact Markdown summary:

| Source | Before | After | Status | Artifacts |
| --- | ---: | ---: | --- | --- |

Then add:

- strongest overlaps
- remaining gaps
- whether the result is review-ready
- exact artifact paths
