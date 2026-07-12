---
name: auto-job-apply
version: 1.3
description: Run the user's configured job-lead sources (e.g. Gmail, Google Jobs, FAANG careers) for the auto-job-apply automation. Use when checking configured sources for software or AI engineering job postings, recruiter threads, or application status emails; curating and deduping leads; scoring roles with the callback MCP/profile; staging review-ready or referral-first applications; updating automation memory; or recording application/rejection/status outcomes without duplicate submissions.
---

# Auto Job Apply

## North Star

Get the user a job by maximizing qualified interview chances: find and score roles that match the candidate's profile criteria (location, work types, and core domains from `get_search_preferences`), avoid duplicate or spammy applications, and never submit an application until the user has reviewed and explicitly approved it in the current turn.

## Candidate Preferences

All curation and gating criteria live in the candidate's callback profile, not in this skill. At run start the parent calls `get_search_preferences` and applies the stored `SearchPreferences`. If none are stored (`next_action=set_search_preferences`), stop and tell the user to run onboard-profile — never fall back to hard-coded criteria.

How to apply each field (the values come from the profile; the interpretation rules below stay fixed):

- **Location gate (hard):** keep only roles matching `home_location` + `work_types` — onsite/hybrid local to the home location, or remote roles explicitly workable from it. Skip roles tied to another metro/state/country or ambiguous about remote-from-home eligibility. Do not reject a strong local in-person/hybrid role.
- **Domain gate:** keep roles primarily inside `core_domains`; skip roles primarily inside `skip_domains` before scoring, even at AI-forward employers. Use `target_titles`/`seniority_bands` to prioritize the queue and `seniority_blockers` to skip. Do not use title/keyword bias to violate the domain gate — still score every plausible in-domain role unless there is a hard blocker.
- **Experience gate (hard blocker):** if a posting states a numeric years-of-experience floor as a *required* (not preferred) qualification and that floor is ≥ `yoe_actual × yoe_gap_multiplier`, skip before scoring with reason "Experience gap: JD requires Nyrs vs ~`yoe_actual`yrs actual" and status `Skipped - hard blocker`. These are typically binary screener knockouts. Do not apply this to soft framing ("5+ years preferred") or ranges that comfortably include the candidate's tenure.
- **Missing-required-skill gate:** if a posting hard-requires ("must have X", "X required") a specific tool/language/domain the candidate has no experience in (judge against the compiled profile), and the role centers on it, skip before scoring — no truthful tailoring can add experience that doesn't exist.
- **Sponsorship gate:** if `needs_sponsorship` is true, skip roles that explicitly deny visa sponsorship. Never ask the user about work authorization — it is stored in `work_authorization`.
- **Compensation (priority, not a gate by default):** prefer roles at/above `comp_annual_target` (in `comp_currency`). Skip below-target roles only when `comp_hard_gate` is true; otherwise still resolve and score them, record the salary (`Not listed`/`Ambiguous`/range), and add a compensation-risk / verify-before-applying note. Equity-only or unclear hourly comp continues through curation.
- **Referral companies:** for a `referral_companies` employer, score and tailor plausible in-domain roles even when the score would be below the normal 70 gate, and surface them as referral leads (see Workflow) so the user can ask for a referral. Use each company's `target_companies` `level_mapping` for level sanity-checks.

## Required Files

These are the canonical single-file locations. There is exactly ONE of each live record file; update it in place. Never create timestamped, run-suffixed, or near-duplicate variants of them.

- Automation memory: `/Users/dandano/.codex/automations/auto-job-apply/memory.md`
- Automation config: `/Users/dandano/.codex/automations/auto-job-apply/automation.toml`
- Canonical record CSV (one only): `/Users/dandano/Documents/Claude/Projects/Job hunt/data/Codex_Job_application_record.csv`
- Job search ledger repo: `/Users/dandano/workplace/job-search-ledger`
- Canonical ledger DB (one only): `/Users/dandano/Documents/Claude/Projects/Job hunt/data/job_search_ledger.sqlite3`
- Canonical Excel tracker (one only): `/Users/dandano/Documents/Claude/Projects/Job hunt/data/Job_application_tracker.xlsx`
- Per-role run artifacts: `/Users/dandano/Documents/Claude/Projects/Job hunt/applications/<YYYY-MM-DD>/<company-role-slug>/`
- Dated backups/exports only under `archive/`: `/Users/dandano/Documents/Claude/Projects/Job hunt/archive/csv_backups/`, `.../archive/xlsx_exports/`, `.../archive/sqlite_backups/`, `.../archive/screenshots/`
- User inputs: `/Users/dandano/Documents/callback-inputs`
- callback repo: `/Users/dandano/workplace/callback`

Read automation memory first. Create the canonical record CSV in place at its path if missing. Keep explanations simple and ADHD-friendly.

## File Output Discipline

These are HARD rules. They override any older path conventions elsewhere in this skill or in automation memory.

- Never write scattered files to the project ROOT `/Users/dandano/Documents/Claude/Projects/Job hunt/`. The canonical live data files live under `data/` (`data/Codex_Job_application_record.csv`, `data/Job_application_tracker.xlsx`, `data/job_search_ledger.sqlite3`), and the automation must update them in place. Never create new variants of them at the project root or anywhere else.
- There is exactly ONE canonical record CSV (`data/Codex_Job_application_record.csv`), ONE tracker (`data/Job_application_tracker.xlsx`), and ONE ledger (`data/job_search_ledger.sqlite3`). Update these in place. Do not create timestamped or run-suffixed copies of them (no `..._2026-06-16.csv`, no `..._run.xlsx`, etc.).
- Per-role run artifacts (resumes, cover letters, JSON, scoring output) go ONLY under `applications/<YYYY-MM-DD>/<company-role-slug>/`. The slug is lowercase, hyphenated, `<company>-<role-keywords>`, e.g. `applications/2026-06-16/netflix-llm-eval/`. One folder per role per day. Reuse the day's existing folder for that role; do not create near-duplicate run folders like `...-run`, `...-rerun`, `...-subtask`, or `...-04pt` for the same role.
- Backups: only when a backup of the record CSV / tracker / ledger is truly needed, write it to `archive/csv_backups/`, `archive/xlsx_exports/`, or `archive/sqlite_backups/` respectively — NEVER to the project root. Prefer NOT creating per-run backups at all; the canonical files plus the archive are sufficient. Only snapshot before a risky bulk edit.
- Screenshots, if any are saved, go under `archive/screenshots/`, not root.

## Run Title

For scheduled automation runs, compute the local America/Los_Angeles date and 24-hour run-start hour. Use this exact title format wherever the host/app allows a conversation or chat title: `Auto Job Apply - YYYY-MM-DD - HH PT`. Also make the first line of the final response exactly `Run title: Auto Job Apply - YYYY-MM-DD - HH PT` with the computed date and hour, not placeholders.

## Orchestrator Model

The parent agent is the run orchestrator. It owns run title, memory, loading `SearchPreferences`, dedupe, applying the location/domain/experience/comp/sponsorship gates, the scoring queue, CSV/job-ledger updates, automation memory updates, and the final user-facing summary.

Use subagents by default for independent work:

- Curator agent (generic, one per enabled source): for each enabled `scan_sources` entry, the parent dispatches one curator agent with that source's `instructions`, its `kind`, and its effective recency (`recency_days` if set, else `lead_recency_days`). The curator follows its instructions to surface leads matching the profile criteria and returns the Discovery Agent Return Contract table only; it must not score, tailor, submit, label, archive, or reply. For `kind: "email"` sources, the curator/parent removes the `UNREAD` label from a message only after the parent has fully reconciled every actionable item in it (recorded/deduped/skipped/scored) — never before. `kind: "careers_page"` sources draw their company list from `target_companies`. All curator output — cards, email summaries, search snippets, job-board rows — is a discovery lead only, even when it looks complete.
- Source resolver agent: takes one discovery lead at a time after the parent dedupes obvious repeats. It follows the email/card/search/job-board URL chain until it reaches an employer careers page, official ATS page, or directly opened third-party page with the complete current JD. It returns source-validation evidence only; it must not score, tailor, submit, label, archive, or reply.
- Callback role agents: one role per agent after the parent validates the full current source and dedupes the queue. Each role agent must use callback directly and must run `load_jd -> submit_keywords -> get_wiki_pages` when useful -> `submit_tailor` with truthful edits. Do not use `no_coverage=True` unless no truthful supported edits exist, and label that result as no-coverage, not tailoring.

If subagent tooling is unavailable, blocked, or inappropriate for a single-role run, the parent may perform the work directly, but it must state that exception in the final summary. For multi-role runs, not using subagents is an exception that must be justified.

### Discovery Agent Return Contract

Each curator agent must return a Markdown table with one row per lead and these columns, even when a field is missing:

| Company | Title | Source URL | Lead URL | Source date | Location/work type | Salary range | Level/seniority | Source status | Relevant info | Blockers/notes |
| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |

Column rules:

- `Source URL`: employer careers URL, official ATS URL, or directly opened third-party full-JD URL when known. Use `Needs source - manual lookup` if only a snippet/email/card URL is available.
- `Lead URL`: the email alert, board card, digest, recruiter email, or search/discovery URL that led to the posting.
- `Source status`: one of `Full source visible`, `Source candidate - needs validation`, `Snippet only`, `Login/blocked`, `Closed`, `Duplicate candidate`, `Compensation risk`, or `Hard blocker`.
- `Relevant info`: short evidence for why the role might fit: stack, domain, level, location, AI/backend/platform/data overlap, requisition ID, posting date, or recruiter context.
- `Blockers/notes`: location risk, source limitation, seniority risk, duplicate clue, clearance issue, domain mismatch, or why the parent should skip before scoring.

The parent must reconcile these tables into one scored queue. Discovery output is never enough to score by itself unless `Source status` is `Full source visible` and the parent verifies the full current source.

### Source Resolver Contract

Run a source-resolution pass before recording `Needs source - not scored` or `Needs source - manual lookup` for any plausible lead from an email alert, LinkedIn, Indeed, ZipRecruiter, Glassdoor, Wellfound, Built In, Dice, The Muse, recruiter email, or another summary/card source.

For each lead, the source resolver must try these steps in order and report which ones succeeded or failed:

1. Open the lead URL or candidate URL from the email/card/search result.
2. Follow any visible `Apply`, `Apply on company site`, `Apply on employer site`, `View job`, or external ATS link.
3. If the page is LinkedIn, Google Jobs, Indeed, ZipRecruiter, Glassdoor, or another aggregator, prefer the employer/ATS outbound link when visible. If the aggregator itself exposes the complete current JD and no employer source is reachable, it may be used as a direct third-party full-JD source.
4. Search the employer career site and web for exact `Company + Title`, `Company + job ID`, and `Company + Title + careers` when the card does not expose a source URL.
5. Check likely official ATS hosts when appropriate: Greenhouse, Lever, Ashby, Workday, SmartRecruiters, Jobvite, iCIMS, Freshteam, Oracle, ADP, BambooHR, Rippling, and company careers pages.
6. Confirm the final source exposes the complete current JD, not only a teaser, search result, preview card, or login-only shell.

Resolver output must include `Source URL`, `Source status`, and `Resolution evidence`. Use `Full source visible` when a complete source is found. Use `Closed`, `Login/blocked`, `Hard blocker`, or `Duplicate candidate` when those are proven. Use `Compensation risk` when the role is otherwise plausible but compensation is below `comp_annual_target` or unclear. Use `Needs source - manual lookup` only after the resolver tried the URL chain plus official-source search and records the failed steps in notes.

## Source Coverage

Sources are data, not hard-coded. Each entry in `scan_sources` is an instruction spec `{name, kind, instructions, enabled, recency_days}`; the parent runs one curator per enabled entry (see Orchestrator Model). **Adding a new job board is a `scan_sources` edit in onboard-profile — never a change to this skill.**

- All discovery output (cards, email summaries, search snippets, job-board rows) is a lead only, never a scoring source — see Source-Only Scoring Rule. Resolve the full current source before scoring.
- `kind: "email"` sources must use an unread constraint (e.g. `is:unread`) and honor the unread→read reconciliation rule; do not scan already-read mail for new discovery unless the user explicitly asks for a backfill/audit.
- `kind: "careers_page"` sources search the official employer source for each `target_companies` entry; prefer the official source over mirrors and capture canonical URL, requisition/job ID, work type, location, salary range, posting date, and visible level.
- Effective recency for a source is its `recency_days` if set, else `lead_recency_days`. Curators must make the recency constraint explicit in their queries/filters.
- **Level sanity-check:** use Levels.fyi and each company's `target_companies` `level_mapping` when level mapping matters; treat bands above the candidate's mapped range as seniority blockers unless the user explicitly asks for a stretch. Do not let missing Levels.fyi data block a clearly good role.
- **Referral leads:** for a `referral_companies` employer, score and tailor plausible in-domain roles regardless of the normal 70-point gate after full-source validation, and surface them as referral leads so the user can ask for a referral before applying.

## Source-Only Scoring Rule

- Score only from the full current job source: the employer careers page, the official ATS page, or a directly opened third-party job page that exposes the complete job description.
- Do not run callback on email snippets, forwarded summaries, job-alert cards, search-result snippets, or partial teaser text. Those are leads, not job descriptions.
- If the source URL opens and exposes the full JD, use `jd_url` when callback can fetch it. If the URL fetch fails but the browser/source page clearly exposes the complete JD, use the full source-page text as `jd_raw_text` and record the source URL in the artifact/notes.
- If no full source URL or full source-page text is available, do not score. Record the row as `Needs source - manual lookup`, include the lead source and any candidate URL, and note that the user needs to find/open the full JD manually.
- A score based on a snippet is not review-ready. If an older snippet-based score exists, label it as historical only and rerun against the full source before staging or applying.

## Workflow

1. Parent reads automation memory, calls `get_search_preferences` and loads the stored criteria (if none are stored, halt and tell the user to run onboard-profile — no hard-coded fallback), computes run title, creates the record CSV if missing, and confirms the run scope/time window.
2. Parent dispatches one curator agent per enabled `scan_sources` entry in parallel when tooling allows, passing each source's `instructions`, `kind`, and effective recency. `kind: "email"` curators use an unread constraint (default `is:unread newer_than:{recency}d`); `kind: "careers_page"` curators search official sources for the `target_companies`. Every source's recency constraint must be explicit.
3. Curator agents expand only promising or status-changing sources and return the Discovery Agent Return Contract table. No curator may score, archive, delete, send, or reply unless the user explicitly asks. Cards and snippets are never scoring sources. For `kind: "email"` sources, once the parent has reconciled the message outcome into the CSV/memory/ledger as applicable, mark the processed message read by removing `UNREAD`; do not mark unread items read while they are still unresolved.
4. Parent merges the discovery tables into a shallow lead list with company, title, source URL, lead URL, source date, salary range, salary source, source type, quick fit reason, and source status. If compensation is not listed, write `Not listed`; do not invent salary.
5. Parent deduplicates against the job search ledger first, then the record CSV while the CSV remains a legacy source. Use this order: exact URL/contact detail, exact requisition/job ID, then exact Title, then Company plus similar Title. If a new URL points to an already-recorded company/title, update the existing row note instead of adding a duplicate.
6. Parent curates before scoring, applying the gates from `SearchPreferences` in order: **location** (`home_location` + `work_types`), then **domain** (keep `core_domains`, skip `skip_domains` before scoring), then the **experience** gate (skip if a required years floor ≥ `yoe_actual × yoe_gap_multiplier`) and the **missing-required-skill** gate (skip if the role centers on a hard-required tool/domain absent from the compiled profile), then the **sponsorship** gate (if `needs_sponsorship`, skip roles that explicitly deny sponsorship). Treat **compensation** as a priority signal unless `comp_hard_gate` is true: prefer roles at/above `comp_annual_target` but still resolve and score below-target roles, recording the salary as `Not listed`/`Ambiguous`/range with a compensation-risk note when below target. Rank the surviving queue by `target_titles`/`core_domains` fit. Also skip hard blockers such as active clearance requirements, closed postings, `seniority_blockers` matches, already-rejected same role/company, or location-gate failures. See Candidate Preferences for how each gate is interpreted.
7. Parent resolves and validates the full current source before scoring or recording a source-limited row. For every plausible non-duplicate discovery lead, either run a source resolver agent or perform the Source Resolver Contract directly. Open the source URL and confirm it exposes the complete JD, not just a card/snippet. If a complete source is found and the role passes the location/domain/seniority gates, score it with callback even when compensation is below `comp_annual_target`. If the role is closed, blocked, duplicate, off-domain, or outside location, record that specific blocker instead of `Needs source`. If compensation is low or unclear, record `Compensation risk` in notes/status but do not skip solely for that reason unless `comp_hard_gate` is true. If the source is unavailable, blocked, login-only, or only an email/search/card snippet remains after the resolver steps, record `Needs source - manual lookup`, include the lead URL/candidate URL, and include the attempted resolver steps in notes.
8. For new plausible in-domain roles at a `referral_companies` employer, parent surfaces them immediately in the final summary as referral leads so the user can ask for a referral before applying. Use status `Referral lead - ask friend` when the role should pause for referral outreach before direct application, but still require a full validated source before scoring. For all other employers, use normal review-gate rules unless the user explicitly names a referral path.
9. Parent dispatches one callback role agent per validated queued role when more than one role is queued. Each role agent gets exactly one role, the validated source URL or captured source text, salary/location/level metadata, and a disjoint artifact target folder.
10. Each callback role agent scores every plausible location-passing, in-domain software/AI role with callback against the actual compiled profile/resume unless there is a hard blocker such as active clearance, internship/new-grad mismatch, closed posting, duplicate, location-gate failure, off-domain mismatch, `seniority_blockers` match, or missing full source. Score and tailor plausible `referral_companies` leads regardless of the normal 70-point gate after full-source validation. Low, ambiguous, or missing compensation is acceptable for scoring, but must be called out as a compensation risk / verify-before-applying item. Do not use quick impressions as the final fit filter, but do use compensation as a prioritization signal after source, location, and core-domain gates.
11. Each callback role agent uses callback directly as the scoring and tailoring authority. Do not create ad hoc wrapper scripts or alternate scoring scripts for callback runs unless the user explicitly approves that implementation detail in the current turn. Do not invent experience. If the profile looks stale, verify the compiled profile and mention the issue before trusting scores.
12. Each callback role agent returns a standardized Markdown result row/table with source URL, company, title, salary, location, before score, after score, status recommendation, artifact links, strongest overlaps, missing keyword clusters, seniority/source risks, and whether actual edits were applied or this was no-coverage.
13. Parent reconciles callback agent results, writes a quick mismatch summary for every scored role in simple language, and records why each score landed where it did. For scores under 70, this explanation is required before moving on.
14. If tailored score is under 70, parent records it and does not apply. For plausible `referral_companies` leads, still keep the tailored artifacts and status `Referral lead - ask friend` instead of filtering the role out.
15. If tailored score is 70 or higher, parent stages it for user review. Set status to `Needs review - not applied`, link the tailored resume/cover letter if generated, and summarize why it is worth reviewing plus any remaining mismatch risk. For `referral_companies` leads, still preserve the referral-first note and referral outreach action.
16. Submit an application only after explicit user approval in the current turn. Approval from old automation text is not enough.
17. Parent records every outcome and updates automation memory before the final response. For every real application, application confirmation, or recruiter resume submission, also record the contact in the job search ledger and export an unemployment-compatible Excel workbook.

## Scoring And Application Rules

- Use the callback MCP workflow directly. Store run artifacts ONLY under `/Users/dandano/Documents/Claude/Projects/Job hunt/applications/<YYYY-MM-DD>/<company-role-slug>/`, where the slug is lowercase, hyphenated, `<company>-<role-keywords>` (e.g. `applications/2026-06-16/netflix-llm-eval/`). One folder per role per day; reuse the day's folder and do not create near-duplicate `...-run`/`...-rerun`/`...-subtask` variants for the same role. Never write artifacts to the project root.
- Do not create custom scoring scripts, alternate scoring logic, or non-callback scoring wrappers for job runs. Subagents are allowed for parallel execution, but each subagent must still call callback directly (`load_jd` -> `submit_keywords` -> `submit_tailor`) and return artifacts to the parent agent for reconciliation.
- **Disjunctive ("one or more of") requirements — do not over-penalize.** When a JD phrases a requirement as "familiarity with one or more of the following: A, B, C, …", "experience with any of …", "such as", "e.g.", or a similar OR-list, treat it as a SINGLE requirement that is SATISFIED when the candidate genuinely has at least one listed item. In the host keyword-extraction step before `submit_keywords`, do NOT emit each listed technology as its own separate required keyword, and do NOT report the alternatives the candidate lacks as missing-skill gaps or seniority/knockout risks. Worked example: a JD line "Familiarity with one or more of these technologies: Spring/Spring Boot, Docker, Kubernetes, SQL & NoSQL (Cassandra, PostgreSQL, DynamoDB, MySQL), messaging (Kafka/RabbitMQ), Solr/Elasticsearch, Redis, etc." is FULLY MET by a candidate who has Docker + SQL + DynamoDB + MySQL — Spring, Cassandra, Kafka, Elasticsearch, and Redis are NOT gaps and must not be listed as missing clusters. Reserve true missing-skill gaps only for requirements phrased as hard, individually-required items ("must have X", "X required", "strong Y experience required"). Read the requirement's connective (one-or-more / any-of / such-as / and vs. or) before deciding whether an un-held tool is actually a gap.
- If callback rendering needs unsandboxed Playwright/Chromium, request permission rather than falling back to guessed scores.
- Never use callback on email-only or snippet-only JD text. The scoring input must come from a full current source URL or complete source-page text captured from that URL.
- Use current web/source checks for postings that may have changed, especially open/closed status, salary/compensation, and level information.
- Capture salary range for each curated/scored/skipped lead from the posting, recruiter email, or current source. If multiple sources disagree, prefer the current employer/recruiter source and mention the conflict. If no salary is listed, record `Not listed` and allow the role to continue if it passes the other gates; note that compensation must be verified before applying. Annualize hourly/contract rates only when the source gives enough information to compute a clear yearly estimate. If the range or annualized estimate is below `comp_annual_target`, mark it as a compensation risk and lower priority; skip solely for compensation only when `comp_hard_gate` is true.
- Use levels.fyi as a sanity check when level mapping matters, but do not let missing levels.fyi data block a clearly good role.
- Treat recruiter threads as follow-up opportunities, not direct applications, unless the user asks to reply.

## Recording

Use the schema and status vocabulary in [record-schema.md](references/record-schema.md). `Recorded Date` is when Codex recorded or acted on the row. `Email Date` is the source Gmail/recruiter/status email timestamp, usually in PT. `Salary range` is required for new rows; use `Not listed` when unavailable.

Always include enough notes to explain future dedupe decisions, salary source, mismatch summary, and next action. The record is the anti-spam ledger.

Use the durable job search ledger for unemployment-reportable contacts:

- Run ledger commands from `/Users/dandano/workplace/job-search-ledger` with `uv run job-search-ledger --db /Users/dandano/Documents/Claude/Projects/Job hunt/data/job_search_ledger.sqlite3 ...`.
- Record reportable contacts only when there was a real application, application confirmation, or recruiter resume submission. Do not mark scored/skipped/needs-review leads as reportable.
- Use strict `ContactType` values: `Online`, `Email`, `Phone`, `In-Person`, `Mail`, `Fax`.
- Use strict `Outcome` values: `Applied`, `No Decision`, `Hired`, `Not Hiring`, `Pending`, `Interviewed`, `Interview Date Set`, `No response from employer`.
- Store callback details as metadata, not as duplicate export columns: `SalaryRange`, `InternalStatus`, `ResumeScoreAfterTailoring`, `ResumeScoreBeforeTailoring`, `ResumePath`, `CoverLetterPath`, and callback run identifiers when useful.
- After recording a reportable contact, run `export-excel` to update the canonical tracker `/Users/dandano/Documents/Claude/Projects/Job hunt/data/Job_application_tracker.xlsx` in place, with its first columns matching the unemployment/EDD schema. Do not create dated or run-suffixed xlsx variants alongside it. If a dated export is genuinely needed (e.g. before a risky bulk edit), write it into `/Users/dandano/Documents/Claude/Projects/Job hunt/archive/xlsx_exports/`, never to the project root or `data/`. If writing the canonical tracker in place is blocked, write the dated export under `archive/xlsx_exports/` and state that a privacy/lock issue prevented updating the canonical workbook directly.

## Final Summary

Use Markdown as the standardized output format. Do not mix plain prose, ad hoc bullets, and inconsistent tables when reporting run results. Use short prose only for context before tables. If the local dashboard has been generated, include its path as a secondary artifact, but the Markdown summary remains the required automation output.

Report:

- Number of jobs found
- Number curated
- Number scored
- Number applied
- Max tailored score
- Mean tailored score
- Min tailored score
- Status emails recorded
- Referral-company leads found, if any, including tailored artifacts and score even when under 70
- Clear review queue, if any
- For each scored role: salary range, final/before scores, status, and a one-line mismatch summary.
- For each skipped role: salary range if available and the blocker/mismatch reason.

If nothing was applied, say that plainly.

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

## Scored Roles
| Company | Title | Source URL | Salary | Location/work type | Before | After | Status | Artifacts | Mismatch summary |
| --- | --- | --- | --- | --- | ---: | ---: | --- | --- | --- |

## Review Queue
| Company | Title | Score | Action needed | Resume | Cover letter | Notes |
| --- | --- | ---: | --- | --- | --- | --- |

## Referral Leads
| Company | Title | Req ID | Level mapping | Source URL | Score | Seniority risk | Referral action | Artifacts |
| --- | --- | --- | --- | --- | ---: | --- | --- | --- |

## Skipped Or Source-Limited
| Company | Title | Source/lead URL | Salary | Reason | Next action |
| --- | --- | --- | --- | --- | --- |
```
