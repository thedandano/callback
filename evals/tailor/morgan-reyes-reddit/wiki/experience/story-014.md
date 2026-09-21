---
type: project
title: DocQuery
job_title: Project
tags:
- Python
- PostgreSQL
- LLM API integration
- Retrieval-augmented search
- Backend
- Data Pipelines
story_type: SBI
timestamp: '2026-09-06T00:00:00+00:00'
---
# DocQuery

**Situation:** New hires on Morgan's team spent their first 2 days searching 500 internal wiki pages to answer basic setup questions, and the same questions kept coming up on the team channel.

**Behavior:** Built DocQuery, a Python service that embeds the wiki pages in a Postgres vector extension and answers questions through an LLM API, so a new hire can ask in plain language instead of searching.

**Impact:** Onboarding-question turnaround for 15 new hires dropped from about 2 days to the same day, and repeat channel questions fell noticeably.
