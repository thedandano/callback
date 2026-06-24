---
name: onboard-profile
description: This skill should be used when the user asks to "onboard my callback profile", "set up my resume profile", "register my resume", "compile my callback profile", "add accomplishments", or prepare callback before tailoring resumes.
version: 0.1.0
---

# Onboard Profile

## North Star

Prepare callback with truthful candidate evidence so future resume tailoring can improve ATS fit without inventing skills, metrics, or experience.

## Use This Skill For

- Registering a resume with callback.
- Loading optional skills or accomplishments source files.
- Compiling the profile wiki after onboarding or after adding stories.
- Creating missing evidence stories when callback reports uncovered or orphaned skills.

## Workflow

1. Confirm the user has a resume path. Accept PDF, DOCX, or TXT paths.
2. Call `onboard_user(resume_path=..., skills_path=..., accomplishments_path=...)`.
3. Read the JSON envelope:
   - If `status` is `error`, explain the error and stop.
   - If `next_action` is `compile_profile`, continue.
4. Call `compile_profile()`. If the user provides a JSON list or dict of story tags, pass it as `story_tags`.
5. Report:
   - registered `resume_label`
   - sections detected from the resume
   - warnings from onboarding
   - `skill_coverage_warnings` from compilation
   - next best action

## Creating Evidence Stories

When callback asks for a missing story, collect only truthful details and call:

`create_story(primary_skill, skills, story_type, job_title, situation, behavior, impact)`

Use concrete SBI-style fields:

- `situation`: where and why the work happened.
- `behavior`: what the candidate personally did.
- `impact`: measured or observable result.

After every `create_story`, call `compile_profile()` again.

## Rules

- Never invent experience, skills, dates, employers, metrics, scope, or tools.
- Treat profile setup as preparation only. Do not tailor a resume in this skill.
- If multiple resumes are registered later, tell tailoring workflows to pass `resume_label`.
- Keep the user-facing summary simple: what was registered, what is missing, and what to do next.
