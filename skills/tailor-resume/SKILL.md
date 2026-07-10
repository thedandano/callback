---
name: tailor-resume
description: Tailors one resume for one job description using callback. Use when the user asks to "tailor my resume", "score this job", "run callback on this JD", "use callback for this job", "make a tailored resume", "apply callback to this posting", or provides one job URL or full job description for resume tailoring.
---

# Tailor Resume

## North Star

Use callback to produce one honest, ATS-aware tailored resume for one validated job description.

## Scope

This is a one-job workflow. Do not scan Gmail, Google Jobs, FAANG careers, CSV ledgers, unemployment trackers, or application forms. Do not submit applications.

## MCP Flow

1. Call `load_jd` with exactly one source:
   - `jd_url` for a current full job page, or
   - `jd_raw_text` for pasted full JD text.
   - Include `resume_label` only when callback reports multiple registered resumes.
2. Extract compact JDData from `data.jd_text` using `data.extraction_protocol`. For disjunctive "one or more of" / "any of" requirement groups, put the alternatives in a `required_any` group (or `preferred_any` when the group sits under a preferred section) — only one is needed, so a candidate who has any single one satisfies it and must not be penalized for lacking the others.
3. Call `submit_keywords(session_id, jd_json)`.
4. Follow `workflow.next_tool`:
   - `get_wiki_pages`: fetch relevant page IDs from `data.wiki_index`, then tailor with that evidence.
   - `submit_tailor`: tailor directly from visible resume evidence.
   - `onboard_user` or `create_story`: stop and explain what profile evidence is missing.
5. Call `submit_tailor(session_id, edits=[...])`, or use `no_coverage=True` only when no truthful supported edits exist.
6. Return `pdf_path`, `archive_path`, before/after scores, accepted/rejected edits, uncovered skills, and a short mismatch summary.

## Tailoring Rules

- Add a keyword only when it is supported by dated experience or clear project evidence.
- Rewrite bullets only when the mechanism and impact are supported by the resume or fetched wiki stories.
- Do not keyword-stuff skills.
- Do not use banned filler language: spearheaded, orchestrated, championed, leveraged, utilized, streamlined, passionate, driven, results-oriented, proven track record.
- Prefer fewer strong edits over many weak edits.

## Output

Use a compact Markdown summary:

| Source | Before | After | Status | Artifacts |
| --- | ---: | ---: | --- | --- |

Then add:

- strongest overlaps
- remaining gaps
- whether the result is review-ready
- exact artifact paths
