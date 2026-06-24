---
name: scan-job-leads
description: This skill should be used when the user asks to "scan job leads", "find job leads", "check Gmail job alerts", "run the job lead scan", "search FAANG careers", "search recent software jobs", or run the scheduled job-search discovery workflow.
version: 0.1.0
---

# Scan Job Leads

## North Star

Find plausible, Anytown-workable software or AI engineering leads while avoiding duplicates, snippets, stale postings, and spammy application behavior.

## Scope

Discovery only. This skill may find, validate, dedupe, and stage leads. It must not submit applications, tailor resumes, reply to recruiters, or mark a role as applied.

## Sources

- Gmail unread job/recruiter/status messages. Queries must include `is:unread` or `label:unread`.
- Current web or Google Jobs style discovery for postings from the last 3 days.
- Official FAANG career/source pages for Meta, Amazon, Apple, Acme, and Google.

## Curation Rules

1. Apply the location gate first:
   - keep Anytown onsite/hybrid roles
   - keep remote roles explicitly workable from Anytown or the United States
   - skip remote roles tied to another metro/state/country
2. Apply the domain gate:
   - prefer backend, platform, data systems, AWS, Python, Java, TypeScript, GenAI, LLM, RAG, MCP, LangGraph, and Bedrock
   - skip heavy firmware, embedded, mobile-only, defense/clearance, support, sales, and unrelated security roles unless the user asks to stretch
3. Treat compensation as priority, not a hard gate:
   - record salary when visible
   - use `Not listed` when missing
   - add compensation-risk notes when the range starts below 150000 USD

## Source Validation

Treat email cards, snippets, search cards, LinkedIn alerts, Indeed digests, and ZipRecruiter summaries as leads only. Before staging a role, resolve a full current source:

- employer careers page
- official ATS page
- directly opened third-party page exposing the complete JD

If no full source is found, record `Needs source - manual lookup` with attempted resolution steps.

## Output

Return a Markdown table:

| Company | Title | Source URL | Lead URL | Salary | Location | Source status | Recommendation | Notes |
| --- | --- | --- | --- | --- | --- | --- | --- | --- |

End with:

- jobs found
- curated leads
- full sources
- source-limited leads
- duplicates/skips
- recommended next action: usually run `review-job-application` on selected full-source leads
