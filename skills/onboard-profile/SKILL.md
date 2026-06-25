---
name: onboard-profile
description: Registers a resume and compiles the callback profile wiki. Use when the user asks to "onboard my callback profile", "set up my resume profile", "register my resume", "compile my callback profile", "add accomplishments", "update my profile", "add a story", or prepare callback before tailoring resumes.
---

# Onboard Profile

## North Star

Prepare callback with truthful candidate evidence so future resume tailoring can improve ATS fit without inventing skills, metrics, or experience. The candidate owns how their experience is organized — your job is to capture their structure faithfully, not to impose one.

## Use This Skill For

- Registering a resume with callback.
- Loading optional skills or accomplishments source files.
- Compiling the profile wiki after onboarding or after adding stories.
- Creating missing evidence stories when callback reports uncovered or orphaned skills.

## How compilation actually works (read this first)

A wrong mental model here causes real, recurring mistakes — so internalize this before doing anything:

- **callback never parses the accomplishments file into stories.** It stores the resume, the raw text, and a list of *created stories*. The profile is compiled only from stories that **you** create with `create_story`.
- **`compile_profile` is deterministic and section-blind.** It aggregates stored stories, builds the skill index, and flags coverage gaps. It does **no** classification — it never looks at `job_title`, never reads the accomplishments headings, and has no concept of "Experience" vs "Projects".
- **`job_title` is a raw passthrough of whatever you pass to `create_story`,** and it is the *only* field that carries where a story belongs. There is no separate section/category field today.

The consequence: **every grouping decision is yours, made at `create_story` time, and frozen permanently.** Re-onboarding recompiles the stored stories verbatim — it does not re-read the file — so an authoring mistake (e.g. tagging a Projects entry with a Freelancing role) silently survives forever. This is exactly why the workflow below gates compilation behind an explicit user check.

## Workflow: Scan → Plan → Confirm → Compile

Do not skip straight to `create_story`/`compile_profile`. Walk the loop.

### 1. Scan

- Confirm the resume path (PDF, DOCX, TXT, or Markdown).
- Read the accomplishments and skills files if provided. Identify the section structure **as the user actually wrote it** — read their headings. Do not assume a fixed taxonomy; one candidate may use Experience / Freelancing / Projects, another Work / Open Source / Volunteering, another something else entirely.
- On a **re-onboard**, also read the already-stored stories (their `job_title`s) so you can diff what's stored against the source and surface drift.

### 2. Plan

Build a proposed mapping — one row per accomplishment entry:

| Entry | Source section | Proposed `job_title` | primary_skill |
|-------|----------------|----------------------|---------------|

Rules for the proposal:
- Derive each `job_title` from **that entry's own section**, never from a neighboring section. Carrying a label across sections (a Projects entry labeled with the Freelancing role) is the single most common failure — guard against it explicitly.
- Because `job_title` is the only grouping signal, propose a **consistent convention** the user can accept or override, e.g. real role titles for employment sections, a literal like `Project` for project sections, `Freelance` for freelance sections. Propose; do not decide unilaterally.
- Flag any entry with no clear skills (so no `primary_skill`) — it can't become a story until that's resolved.

### 3. Confirm

Present the plan and ask the user to verify, in plain terms:
- the **sections** you detected,
- the **`job_title` each story will get** (i.e. how it will be grouped),
- and call out, briefly, that callback has no separate section field, so `job_title` *is* the grouping — which is why their sign-off matters.

Wait for approval. If the user wants changes, revise the table and re-present. Do not compile on assumptions.

### 4. Compile (only after approval) or iterate

- For each approved entry that isn't already a faithful stored story, call `create_story(primary_skill, skills, story_type, job_title, situation, behavior, impact)` with the agreed `job_title`.
- On a re-onboard, correct any drifted stories to match the approved plan before compiling.
- Then call `compile_profile()` (pass `story_tags` only if the user supplies a JSON list/dict).
- After every `create_story`, call `compile_profile()` again.

### 5. Report

- registered `resume_label`
- sections detected, and the confirmed story → `job_title` grouping
- onboarding warnings and `skill_coverage_warnings`
- next best action

## Creating Evidence Stories

When callback reports a missing/orphaned skill, collect only truthful details and create a story. Use concrete SBI-style fields:

- `situation`: where and why the work happened.
- `behavior`: what the candidate personally did.
- `impact`: measured or observable result.

Set `job_title` per the confirmed plan (step 3), not by guesswork. After every `create_story`, call `compile_profile()` again.

## Rules

- Never invent experience, skills, dates, employers, metrics, scope, or tools.
- Never carry a `job_title`/grouping label across sections; derive it from the entry's own section.
- Always confirm the section structure and grouping with the user before compiling.
- Treat profile setup as preparation only. Do not tailor a resume in this skill.
- If multiple resumes are registered later, tell tailoring workflows to pass `resume_label`.
- Keep the user-facing summary simple: what was registered, what is missing, and what to do next.
