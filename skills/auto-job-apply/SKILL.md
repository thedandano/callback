---
name: auto-job-apply
version: 1.2
description: Run the user's Gmail, Google Jobs, and FAANG careers job lead workflow for the auto-job-apply automation. Use when checking Gmail, Google Jobs, or FAANG careers for software or AI engineering job postings, recruiter threads, or application status emails; curating and deduping leads; scoring roles with the Callback MCP/profile; staging review-ready or referral-first applications; updating automation memory; or recording application/rejection/status outcomes without duplicate submissions.
---

# Auto Job Apply

## North Star

Get the user a job by maximizing qualified interview chances: find and score San Diego-area or remote-workable software/AI engineering roles inside the user's core domains, avoid duplicate or spammy applications, and never submit an application until the user has reviewed and explicitly approved it in the current turn.

## Candidate Preferences

- Location: user lives in San Diego. Curate only San Diego-area in-person, San Diego-area hybrid, or remote roles that are explicitly workable from San Diego.
- Treat location as a hard curation gate. Do not curate non-San-Diego onsite or hybrid roles.
- Do not curate remote roles that are tied to another metro/state/country, require residence outside San Diego/California, or are ambiguous about whether the user can work from San Diego.
- Do not reject a strong role just because it is in-person or hybrid when it is local to San Diego.
- Target: mid-level FAANG-caliber software engineer, possibly senior at smaller companies, with interest in AI Engineer transition roles.
- Compensation priority: prefer roles whose current source, recruiter message, or complete validated posting suggests annualized base/pay at or above $150,000/year, but do not use $150,000 as a hard curation or scoring gate. If a role is otherwise strong but the listed range starts below $150,000, still resolve the full source and score it, then record the salary and note compensation risk / verify before applying. Ambiguous, missing, equity-only, or unclear hourly compensation is allowed to continue through curation/scoring; record the salary as `Not listed` or `Ambiguous` and note that compensation must be verified before applying.
- Core domains: backend/platform/data systems, AWS/Python/Java/TypeScript service ownership, distributed systems, microservices, REST APIs, data pipelines, schema/data validation, CI/CD, testing, service ownership, developer tooling, internal platforms, data engineering, pricing/compliance systems, GenAI, LLMs, RAG, agentic AI, MCP, LangGraph, and Amazon Bedrock.
- Bias search and curation toward SWE, Software Engineer, AI Engineer, backend/platform/data systems, AWS, Python, Java, TypeScript, distributed systems, microservices, REST APIs, data pipelines, schema/data validation, CI/CD, testing, service ownership, pricing/compliance systems, internal tooling, GenAI, LLMs, RAG, agentic AI, MCP, LangGraph, and Amazon Bedrock.
- Treat these as weak or skip-before-scoring domains unless paired with unusually strong backend/AI evidence and explicit user interest: embedded, firmware, kernel, Linux distribution support, C/C++-heavy systems, mobile/game SDKs, mobile-only, frontend-only, cybersecurity/SIEM/SOAR/cloud-security architecture, battery/energy-domain platforms, sales/GTM, support operations, defense/clearance, HR/compensation SaaS, and commerce/order roles centered on Redis/MQ/RPC/high-concurrency operations without AWS/data-platform overlap.
- Do not use keyword bias to violate the domain filter: still score every plausible San Diego-area or remote-workable role inside the core domains unless there is a hard blocker, but skip roles primarily outside those domains before scoring. Use the bias to prioritize the queue, explain mismatch, and avoid spending time on off-domain roles.

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
- User inputs: `/Users/dandano/Documents/go-apply-inputs`
- Callback repo: `/Users/dandano/workplace/callback`
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

The parent agent is the run orchestrator. It owns run title, memory, source policy, dedupe, location/domain gates, scoring queue, CSV/job-ledger updates, automation memory updates, and the final user-facing summary.

Use subagents by default for independent work:

- Gmail curator agent: searches unread Gmail job alerts, recruiter threads, application confirmations, rejection/status emails, and forwarded job snippets only. It returns discovery leads only; it must not score, tailor, submit, label, archive, or reply. After the parent has recorded, deduped, skipped, scored, or otherwise fully handled every actionable item from a message, the Gmail curator or parent should mark that processed message as read by removing `UNREAD`. Do not mark messages read before they have been reconciled.
- Google Jobs curator agent: searches Google Jobs or current web search results for jobs that appeared within the last 3 days only. It targets San Diego-area or San Diego-workable remote SWE, Software Engineer, AI Engineer, GenAI/LLM/RAG, backend/platform/data engineering, AWS/Python/Java/TypeScript roles. It returns discovery leads only; it must not score, tailor, submit, label, archive, or reply. Google Jobs cards, search-result snippets, and job-board summary cards are discovery leads only, even when they look complete.
- FAANG curator agent: searches current official careers/source pages for Meta, Amazon, Apple, Netflix, and Google. It targets remote or San Diego-area SWE, Software Engineer, Software Engineering, AI Engineer, GenAI/ML/platform/backend/data roles. It returns FAANG source leads only; it must not score or tailor. Netflix-specific referral, source, and level rules still apply inside this broader FAANG agent.
- Source resolver agent: takes one discovery lead at a time after the parent dedupes obvious repeats. It follows the email/card/search/job-board URL chain until it reaches an employer careers page, official ATS page, or directly opened third-party page with the complete current JD. It returns source-validation evidence only; it must not score, tailor, submit, label, archive, or reply.
- Callback role agents: one role per agent after the parent validates the full current source and dedupes the queue. Each role agent must use Callback directly and must run `load_jd -> submit_keywords -> get_wiki_pages` when useful -> `submit_tailor` with truthful edits. Do not use `no_coverage=True` unless no truthful supported edits exist, and label that result as no-coverage, not tailoring.
  If subagent tooling is unavailable, blocked, or inappropriate for a single-role run, the parent may perform the work directly, but it must state that exception in the final summary. For multi-role runs, not using subagents is an exception that must be justified.

### Discovery Agent Return Contract

Each Gmail, Google Jobs, and FAANG curator agent must return a Markdown table with one row per lead and these columns, even when a field is missing:

| Company | Title | Source URL | Lead URL | Source date | Location/work type | Salary range | Level/seniority | Source status | Relevant info | Blockers/notes |
| ------- | ----- | ---------- | -------- | ----------- | ------------------ | ------------ | --------------- | ------------- | ------------- | -------------- |

Column rules:

- `Source URL`: employer careers URL, official ATS URL, Netflix source URL, or directly opened third-party full-JD URL when known. Use `Needs source - manual lookup` if only a snippet/email/card URL is available.
- `Lead URL`: Gmail alert, LinkedIn card, Indeed/ZipRecruiter digest, recruiter email, or search/discovery URL that led to the posting.
- `Source status`: one of `Full source visible`, `Source candidate - needs validation`, `Snippet only`, `Login/blocked`, `Closed`, `Duplicate candidate`, `Compensation risk`, or `Hard blocker`.
- `Relevant info`: short evidence for why the role might fit: stack, domain, level, location, AI/backend/platform/data overlap, requisition ID, posting date, or recruiter context.
- `Blockers/notes`: location risk, source limitation, seniority risk, duplicate clue, clearance issue, domain mismatch, or why the parent should skip before scoring.
  The parent must reconcile these tables into one scored queue. Discovery output is never enough to score by itself unless `Source status` is `Full source visible` and the parent verifies the full current source.

### Source Resolver Contract

Run a source-resolution pass before recording `Needs source - not scored` or `Needs source - manual lookup` for any plausible lead from Gmail, Google Jobs, LinkedIn, Indeed, ZipRecruiter, Glassdoor, Wellfound, Built In, Dice, The Muse, recruiter email, or another summary/card source.

For each lead, the source resolver must try these steps in order and report which ones succeeded or failed:

1. Open the lead URL or candidate URL from the email/card/search result.
2. Follow any visible `Apply`, `Apply on company site`, `Apply on employer site`, `View job`, or external ATS link.
3. If the page is LinkedIn, Google Jobs, Indeed, ZipRecruiter, Glassdoor, or another aggregator, prefer the employer/ATS outbound link when visible. If the aggregator itself exposes the complete current JD and no employer source is reachable, it may be used as a direct third-party full-JD source.
4. Search the employer career site and web for exact `Company + Title`, `Company + job ID`, and `Company + Title + careers` when the card does not expose a source URL.
5. Check likely official ATS hosts when appropriate: Greenhouse, Lever, Ashby, Workday, SmartRecruiters, Jobvite, iCIMS, Freshteam, Oracle, ADP, BambooHR, Rippling, and company careers pages.
6. Confirm the final source exposes the complete current JD, not only a teaser, search result, preview card, or login-only shell.
   Resolver output must include `Source URL`, `Source status`, and `Resolution evidence`. Use `Full source visible` when a complete source is found. Use `Closed`, `Login/blocked`, `Hard blocker`, or `Duplicate candidate` when those are proven. Use `Compensation risk` when the role is otherwise plausible but compensation is below the preferred target or unclear. Use `Needs source - manual lookup` only after the resolver tried the URL chain plus official-source search and records the failed steps in notes.

## Source Coverage

- Gmail: Search only unread recent job postings, recruiter threads, job alerts, application confirmations, and rejection/status messages. Gmail queries must include an unread constraint such as `is:unread` or `label:unread`; do not scan already-read mail for new discovery unless the user explicitly asks for a backfill/audit. Treat Gmail, forwarded Indeed snippets, LinkedIn alert cards, ZipRecruiter digests, and other email summaries as discovery leads only, not scoring sources. After the parent fully handles a Gmail message by recording/deduping/skipping/scoring all relevant items in it, remove the `UNREAD` label from that message so the same alert is not processed again.
- Google Jobs: Search Google Jobs or current web search results every run for jobs that appeared within the last 3 days. Use query/time filters that make the 3-day recency constraint explicit. Search for San Diego and remote-workable SWE, Software Engineer, AI Engineer, GenAI/LLM/RAG, backend/platform/data, AWS, Python, Java, and TypeScript roles. Treat Google Jobs cards and snippets as discovery only. Before scoring, open the employer careers page, official ATS page, or directly opened third-party full-JD page and confirm it exposes the complete current JD. If no complete source can be opened, record `Needs source - manual lookup` and do not score.
- FAANG careers: Search current official source/careers pages for Meta, Amazon, Apple, Netflix, and Google every run. Prefer the employer's official source over third-party mirrors. Capture canonical URL, requisition/job ID, work type, location, salary range, posting date, and visible level when present. Apply the same source-only scoring, location, compensation-priority, and core-domain rules as all other roles.
- FAANG level mapping: use Levels.fyi as a sanity check when level mapping matters. Plausible target bands are Meta E4/E5, Google L4/L5, Amazon L5/SDE II, Apple ICT3/ICT4, and Netflix L4/E4/Software Engineer II. Treat staff/principal bands as hard seniority blockers unless the user explicitly asks for a stretch.
- Netflix level mapping: use Levels.fyi as a sanity check. Amazon L5 / SDE II maps closest to Netflix L4 / E4 / Software Engineer II, not Netflix L5. Do not curate or score Netflix L5 / E5 / Senior Software Engineer roles by default. Netflix L6+ / E6+ is staff-level and should be skipped as a seniority blocker. Only score Netflix L5+ roles when the user explicitly names a specific referral stretch in the current turn.
- For plausible Netflix L4 / E4 / Software Engineer II or clearly mid-level Netflix roles inside the core domains, score and tailor even when the score would normally be below 70; the goal is to give the user enough evidence and artifacts to ask their friend for a referral.

## Source-Only Scoring Rule

- Score only from the full current job source: the employer careers page, the official ATS page, or a directly opened third-party job page that exposes the complete job description.
- Do not run Callback on email snippets, forwarded summaries, job-alert cards, search-result snippets, or partial teaser text. Those are leads, not job descriptions.
- If the source URL opens and exposes the full JD, use `jd_url` when Callback can fetch it. If the URL fetch fails but the browser/source page clearly exposes the complete JD, use the full source-page text as `jd_raw_text` and record the source URL in the artifact/notes.
- If no full source URL or full source-page text is available, do not score. Record the row as `Needs source - manual lookup`, include the lead source and any candidate URL, and note that the user needs to find/open the full JD manually.
- A score based on a snippet is not review-ready. If an older snippet-based score exists, label it as historical only and rerun against the full source before staging or applying.

## Workflow

1. Parent reads automation memory, computes run title, creates the record CSV if missing, and confirms the run scope/time window.
2. Parent dispatches the Gmail curator agent, Google Jobs curator agent, and FAANG curator agent in parallel when tooling allows. Use the requested Gmail time window, but always constrain Gmail discovery to unread messages; default to `is:unread newer_than:3d` for reruns like "last 3 days". Google Jobs discovery must always be constrained to postings that appeared within the last 3 days. FAANG discovery should search official source/careers pages for Meta, Amazon, Apple, Netflix, and Google.
3. Discovery agents expand only promising or status-changing sources and return the Discovery Agent Return Contract table. Gmail agents must not archive, delete, send, or reply unless the user explicitly asks. Google Jobs agents must not score from Google Jobs cards or search snippets. FAANG agents must prefer official employer source pages and preserve Netflix-specific referral/level notes. Once the parent has reconciled the message outcome into the CSV/memory/ledger as applicable, mark the processed Gmail message as read by removing `UNREAD`; do not mark unread items read while they are still unresolved.
4. Parent merges the discovery tables into a shallow lead list with company, title, source URL, lead URL, source date, salary range, salary source, source type, quick fit reason, and source status. If compensation is not listed, write `Not listed`; do not invent salary.
5. Parent deduplicates against the job search ledger first, then the record CSV while the CSV remains a legacy source. Use this order: exact URL/contact detail, exact requisition/job ID, then exact Title, then Company plus similar Title. If a new URL points to an already-recorded company/title, update the existing row note instead of adding a duplicate.
6. Parent curates before scoring. Apply the location gate first: keep only San Diego-area onsite/hybrid roles or remote roles explicitly workable from San Diego. Then apply the core-domain gate: keep roles primarily in backend/platform/data systems, AWS/Python/Java/TypeScript service ownership, developer tooling/internal platforms, data engineering, or GenAI/LLM/RAG/agentic AI. Skip roles primarily centered on mobile/game SDKs, cybersecurity/SIEM/SOAR/cloud-security architecture, battery/energy-domain platforms, support operations, hardware/firmware, defense/clearance, or other niche domains unless the user explicitly asks to stretch. Treat compensation as a priority signal, not a hard gate: prefer roles at or above $150,000/year, but still resolve and score otherwise strong roles below that target. Record the salary as `Not listed`, `Ambiguous`, or the posted range, and add a compensation-risk note when the range starts below $150,000 or the true San Diego-workable floor is unclear. Then rank by the keyword-bias clusters above, with strongest weight for SWE, AI Engineer, backend/platform/data/AWS/Python/Java/TypeScript plus AI-transition terms. Skip hard blockers such as active clearance requirements, closed postings, heavy embedded/firmware/C++ mismatch, obvious seniority mismatch, already-rejected same role/company, or clearly non-San-Diego location.
7. Parent resolves and validates the full current source before scoring or recording a source-limited row. For every plausible non-duplicate discovery lead, either run a source resolver agent or perform the Source Resolver Contract directly. Open the source URL and confirm it exposes the complete JD, not just a card/snippet. If a complete source is found and the role passes location/core-domain/seniority gates, score it with Callback even when compensation is below the preferred target. If the role is closed, blocked, duplicate, off-domain, or outside location, record that specific blocker instead of `Needs source`. If compensation is low or unclear, record `Compensation risk` in notes/status but do not skip solely for that reason. If the source is unavailable, blocked, login-only, or only an email/search/card snippet remains after the resolver steps, record `Needs source - manual lookup`, include the lead URL/candidate URL, and include the attempted resolver steps in notes.
8. For new plausible mid-level Netflix roles inside the core domains, parent surfaces them immediately in the final summary as referral leads so the user can ask their friend for a referral before applying. Use status `Referral lead - ask friend` when the role should pause for referral outreach before direct application, but still require a full Netflix source or full source-page text before scoring. For non-Netflix FAANG roles, use normal review-gate rules unless the user explicitly names a referral path.
9. Parent dispatches one Callback role agent per validated queued role when more than one role is queued. Each role agent gets exactly one role, the validated source URL or captured source text, salary/location/level metadata, and a disjoint artifact target folder.
10. Each Callback role agent scores every plausible San Diego-area SWE, Software Engineer, AI Engineer, or adjacent software/AI role inside the core domains with Callback against the actual compiled profile/resume unless there is a hard blocker such as active clearance, internship/new-grad mismatch, closed posting, duplicate, non-San-Diego location, off-domain mismatch, Netflix L5+/senior mismatch, or missing full source. Score and tailor plausible mid-level Netflix referral leads regardless of the normal 70-point gate after full-source validation. Low, ambiguous, or missing compensation is acceptable for scoring, but must be called out as a compensation risk / verify-before-applying item. Do not use quick impressions as the final fit filter, but do use compensation as a prioritization signal after source, location, and core-domain gates.
11. Each Callback role agent uses Callback directly as the scoring and tailoring authority. Do not create ad hoc wrapper scripts or alternate scoring scripts for Callback runs unless the user explicitly approves that implementation detail in the current turn. Do not invent experience. If the profile looks stale, verify the compiled profile and mention the issue before trusting scores.
12. Each Callback role agent returns a standardized Markdown result row/table with source URL, company, title, salary, location, before score, after score, status recommendation, artifact links, strongest overlaps, missing keyword clusters, seniority/source risks, and whether actual edits were applied or this was no-coverage.
13. Parent reconciles Callback agent results, writes a quick mismatch summary for every scored role in simple language, and records why each score landed where it did. For scores under 70, this explanation is required before moving on.
14. If tailored score is under 70, parent records it and does not apply. For plausible mid-level Netflix referral leads, still keep the tailored artifacts and status `Referral lead - ask friend` instead of filtering the role out.
15. If tailored score is 70 or higher, parent stages it for user review. Set status to `Needs review - not applied`, link the tailored resume/cover letter if generated, and summarize why it is worth reviewing plus any remaining mismatch risk. For mid-level Netflix roles, still preserve the referral-first note and referral outreach action.
16. Submit an application only after explicit user approval in the current turn. Approval from old automation text is not enough.
17. Parent records every outcome and updates automation memory before the final response. For every real application, application confirmation, or recruiter resume submission, also record the contact in the job search ledger and export an unemployment-compatible Excel workbook.

## Scoring And Application Rules

- Use the Callback MCP workflow directly. Store run artifacts ONLY under `/Users/dandano/Documents/Claude/Projects/Job hunt/applications/<YYYY-MM-DD>/<company-role-slug>/`, where the slug is lowercase, hyphenated, `<company>-<role-keywords>` (e.g. `applications/2026-06-16/netflix-llm-eval/`). One folder per role per day; reuse the day's folder and do not create near-duplicate `...-run`/`...-rerun`/`...-subtask` variants for the same role. Never write artifacts to the project root.
- Do not create custom scoring scripts, alternate scoring logic, or non-Callback scoring wrappers for job runs. Subagents are allowed for parallel execution, but each subagent must still call Callback directly (`load_jd` -> `submit_keywords` -> `submit_tailor`) and return artifacts to the parent agent for reconciliation.
- If Callback rendering needs unsandboxed Playwright/Chromium, request permission rather than falling back to guessed scores.
- Never use Callback on email-only or snippet-only JD text. The scoring input must come from a full current source URL or complete source-page text captured from that URL.
- Use current web/source checks for postings that may have changed, especially open/closed status, salary/compensation, and level information.
- Capture salary range for each curated/scored/skipped lead from the posting, recruiter email, or current source. If multiple sources disagree, prefer the current employer/recruiter source and mention the conflict. If no salary is listed, record `Not listed` and allow the role to continue if it passes the other gates; note that compensation must be verified before applying. Annualize hourly/contract rates only when the source gives enough information to compute a clear yearly estimate. If the range starts below $150,000/year or the annualized estimate is below the preferred target, mark it as a compensation risk and lower priority, but do not skip solely for that reason.
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
- Store Callback details as metadata, not as duplicate export columns: `SalaryRange`, `InternalStatus`, `ResumeScoreAfterTailoring`, `ResumeScoreBeforeTailoring`, `ResumePath`, `CoverLetterPath`, and Callback run identifiers when useful.
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
- Mid-level Netflix referral leads found, if any, including tailored artifacts and score even when under 70
- Clear review queue, if any
- For each scored role: salary range, final/before scores, status, and a one-line mismatch summary.
- For each skipped role: salary range if available and the blocker/mismatch reason.
  If nothing was applied, say that plainly.

### Final Markdown Template

```markdown
Run title: Auto Job Apply - YYYY-MM-DD - HH PT

## Stats

| Jobs found | Curated | Scored | Applied | Max score | Mean score | Min score | Status emails | Source-manual leads | Netflix referral leads |
| ---------: | ------: | -----: | ------: | --------: | ---------: | --------: | ------------: | ------------------: | ---------------------: |
|          0 |       0 |      0 |       0 |       N/A |        N/A |       N/A |             0 |                   0 |                      0 |

## Discovery Sources

| Source agent        | Leads returned | Full sources | Needs manual source | Notes                                                  |
| ------------------- | -------------: | -----------: | ------------------: | ------------------------------------------------------ |
| Gmail curator       |              0 |            0 |                   0 |                                                        |
| Google Jobs curator |              0 |            0 |                   0 | Last-3-days discovery only.                            |
| FAANG curator       |              0 |            0 |                   0 | Meta, Amazon, Apple, Netflix, Google official sources. |

## Scored Roles

| Company | Title | Source URL | Salary | Location/work type | Before | After | Status | Artifacts | Mismatch summary |
| ------- | ----- | ---------- | ------ | ------------------ | -----: | ----: | ------ | --------- | ---------------- |

## Review Queue

| Company | Title | Score | Action needed | Resume | Cover letter | Notes |
| ------- | ----- | ----: | ------------- | ------ | ------------ | ----- |

## Netflix Referral Leads

| Company | Title | Req ID | Level mapping | Source URL | Score | Seniority risk | Referral action | Artifacts |
| ------- | ----- | ------ | ------------- | ---------- | ----: | -------------- | --------------- | --------- |

## Skipped Or Source-Limited

| Company | Title | Source/lead URL | Salary | Reason | Next action |
| ------- | ----- | --------------- | ------ | ------ | ----------- |
```
