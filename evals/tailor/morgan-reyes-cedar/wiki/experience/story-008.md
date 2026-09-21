---
type: story
title: SQL
job_title: Backend & Data Engineer
tags:
- SQL
- PostgreSQL
- Query Optimization
- Data Warehousing
- Backend
- Python
- Code Review
- CI/CD
- Relational Data Modeling
- Data Pipelines
story_type: SBI
timestamp: '2026-09-06T00:00:00+00:00'
---
# SQL

**Situation:** The 15 slowest queries in the analytics warehouse were responsible for most of the 12-second average dashboard load time that 8 downstream teams complained about.

**Behavior:** Profiled execution plans for the 15 slowest queries and rewrote them with better join order, targeted indexes, and query optimization to cut redundant table scans.

**Impact:** Average dashboard load time fell from 12 seconds to 2 seconds across all 8 downstream teams.
