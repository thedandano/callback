---
type: story
title: CDC
job_title: Backend & Data Engineer
tags:
- CDC
- PostgreSQL
- Data Warehousing
- Relational Data Modeling
- Backend
- SQL
- Python
- Query Optimization
- Code Review
- CI/CD
story_type: SBI
timestamp: '2026-09-06T00:00:00+00:00'
---
# CDC

**Situation:** Downstream teams pulled from Anchor's PostgreSQL analytics tables directly, so a schema change in the source could silently corrupt 3 finance dashboards overnight.

**Behavior:** Introduced change data capture (CDC) as the contract between the source PostgreSQL tables and 8 downstream teams, with a documented star schema behind it.

**Impact:** Zero silent schema breaks in the 18 months after rollout, down from 2 incidents the year before.
