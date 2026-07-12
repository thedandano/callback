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
- Capturing durable search preferences + PII (location, work types, domains, curator sources, comp, sponsorship, work authorization, actual years of experience) via `set_search_preferences`.

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

## Preferences & PII Interview

After the story workflow, capture the durable job-search criteria so downstream skills (scan-job-leads, auto-job-apply) read them from the profile instead of hard-coding. These persist in callback's `SearchPreferences` store via `set_search_preferences`.

**Profile boundary:** the durable profile = compiled stories + these preferences. Raw input files under `callback-inputs/` (resume PDF, accomplishments, skills reference) are one-time source material, **not** the profile — never treat them as the live source of truth for criteria.

### 1. Read current values

Call `get_search_preferences`. If it returns `next_action=set_search_preferences`, none are stored yet (first onboard). Otherwise show each stored value as the default the user can keep or change (re-onboard).

### 2. Interview (one topic at a time)

Collect, confirming each; never invent an answer:

- `home_location` (string) and `work_types` (any of `onsite_local`, `hybrid_local`, `remote`) — the hard location gate.
- `target_titles`, `seniority_bands`, `seniority_blockers` — role bias + knockouts.
- `target_companies` — each `{name, level_mapping}` (e.g. Amazon `L5/SDE II == mid`); this is where FAANG level bands live.
- `core_domains` / `skip_domains` — the domain gate.
- `comp_currency`, `comp_annual_target`, and `comp_hard_gate` — set `comp_hard_gate=true` only if the user wants to skip below-target roles; default `false` (target is a priority signal, not a gate).
- `referral_companies` — each `{name, note}` (e.g. Netflix, "ask friend for referral").
- `lead_recency_days` — default 3.
- **PII (ask directly; do not assume):** `needs_sponsorship` (bool), `work_authorization` (e.g. "US Citizen", "H-1B needs transfer"), `yoe_actual` (real total years — drives the experience gate), `yoe_gap_multiplier` (default 1.75; skip a role when its required years ≥ `yoe_actual × this`).

### 3. Curators (`scan_sources`) — instruction specs

Each source is a portable instruction spec, not a fixed name the skill hard-codes: `{name, kind, instructions, enabled, recency_days}`. `kind` is one of `email`, `web_search`, `careers_page`, `job_board` (free-form; unrecognized kinds run as generic web/browser curators). `instructions` is freeform text telling the curator how to search that source and what to return. `recency_days` overrides `lead_recency_days` for that source.

Seed three defaults, letting the user edit each:

- `{name: "gmail", kind: "email", instructions: "Search is:unread newer_than:{recency}d job alerts, recruiter threads, application confirmations, rejection/status. Return discovery leads only. After the parent reconciles a message, remove the UNREAD label."}`
- `{name: "google_jobs", kind: "web_search", instructions: "Search Google Jobs / web for postings from the last {recency} days matching target titles/domains, home_location + remote-workable. Cards and snippets are discovery only."}`
- `{name: "faang_careers", kind: "careers_page", instructions: "Search official careers pages for the target_companies. Prefer official employer source over mirrors. Capture canonical URL, req ID, work type, location, salary, posting date, level."}`

Tell the user: **adding a new job board later is just another `scan_sources` entry here — no skill edit.**

### 4. Persist

Send **one** `set_search_preferences` call with the complete object. It is a full replace — include every field, not just the changed ones, or omitted fields revert to defaults.

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
