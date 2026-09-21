---
type: story
title: PostgreSQL
job_title: Backend & Data Engineer
tags:
- PostgreSQL
- SQL
- Python
- CDC
- Data Warehousing
- Backend
- Query Optimization
- Code Review
- CI/CD
- GitHub Actions
- Relational Data Modeling
- Data Pipelines
- Test-Driven Development
story_type: SBI
timestamp: '2026-09-06T00:00:00+00:00'
---
# PostgreSQL

**Situation:** Anchor's analytics warehouse ran a full-table PostgreSQL refresh every night, and the 200GB job routinely ran past the 6-hour maintenance window into business hours.

**Behavior:** Rebuilt the load in Python and SQL around incremental change data capture (CDC) from the PostgreSQL source tables, replacing the nightly full refresh.

**Impact:** The load window dropped from 6 hours to 45 minutes and the warehouse was never late again during my 2 years there.
