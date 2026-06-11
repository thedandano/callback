# Retro — callback v1.0.0: LangSmith observability, rename, migration

**Date:** 2026-06-11
**Scope:** PR #44 (LangSmith threads + redacted I/O), PR #47 (rename pi-apply → callback), v1.0.0 release, PR #49 (post-rename sweep), local environment migration.

## What shipped

- **LangSmith observability (0.5.0):** the 4 interrupt-separated apply tool calls now group
  into one LangSmith Thread via `session_id`/`thread_id` stamped on every span; trace I/O
  carries full content (JD text, keywords, edits, scores) with contact-PII redacted
  (`_redact_pii`: email/phone anywhere, name/location/url only inside the contact block).
- **Rename + v1.0.0:** package/CLI/dist all `callback`, env prefix `CALLBACK_*`, data dirs
  `~/.local/share|state/callback/`, repo `thedandano/callback`, released via
  `Release-As: 1.0.0` footer through release-please.
- **Migration:** uv tool reinstalled as `callback`, `~/.claude.json` MCP registration + env
  vars + project key migrated, serena config path fixed, cwd-sensitive hooks hardened,
  project memory copied to the new key.

## What bit us (and the fix)

1. **Interrupts split traces.** Host-handoff interrupts mean each MCP tool call is its own
   LangSmith trace; there is no shared parent context. Fix was Threads (metadata
   `session_id`), not forcing a single trace tree — work with the platform's model.
2. **Global key-based redaction over-redacted.** First pass redacted every `name` key,
   which would have blanked `ProjectEntry.name` (project titles). Caught by spec review
   against the locked scope ("contact header only"). Lesson: redaction scope must be
   expressed structurally (contact block detection), not lexically.
3. **Dead-cwd hook error after directory rename.** Renaming the repo directory mid-session
   broke `serena-hooks` (stale project path in `~/.serena/serena_config.yml`) — that was the
   visible hook error. The bash/python hooks were near-tolerant already; hardened anyway
   (cd-guard + try/except OSError). Lesson: directory renames invalidate every absolute-path
   registration (serena, MCP command, uv tool editable install, Claude project key).
4. **Token replace only covers tracked files.** The rename commit's replace ran over
   `git grep` results, so untracked/local files (`.claude/commands/apply.md`, most
   `openspec/specs/`) kept stale references until the post-rename sweep. Lesson: after a
   rename, sweep untracked project files separately.
5. **`Release-As` footer + rebase-merge** is the clean way to force a major version through
   release-please; squash-merge would have needed the footer duplicated in the PR body.

## Process notes

- Subagent-driven development with two-stage review (spec, then quality) caught both real
  defects (dead fallback path; over-redaction) before merge — the review loop paid for itself.
- Naming decision (callback) validated against PyPI availability before committing; the
  distribution name was genuinely free despite being a common word.

## Follow-ups

- Restart Claude Code sessions in `~/workplace/callback` so the new MCP
  registration (`callback`) and serena project activate.
- Verify the Threads grouping in the LangSmith UI (`Callback` project) on the next live run.
- Old `~/.claude/projects/-REDACTED-workplace-pi-apply/` dir left in place; delete once
  confident nothing else reads it.
