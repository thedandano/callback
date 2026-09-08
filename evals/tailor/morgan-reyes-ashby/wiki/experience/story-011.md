---
type: story
title: GitHub Actions
job_title: Backend & Data Engineer
tags:
- GitHub Actions
- CI/CD
- Code Review
- Python
- Data Pipelines
- PostgreSQL
- SQL
- Backend
- Test-Driven Development
- Query Optimization
- Data Warehousing
- Relational Data Modeling
story_type: SBI
timestamp: '2026-09-06T00:00:00+00:00'
---
# GitHub Actions

**Situation:** Anchor's data pipelines shipped through a manual deploy checklist, and a release could go out with an untested query change since nothing blocked the merge.

**Behavior:** Set up a GitHub Actions CI/CD pipeline that ran the test suite, linted SQL migrations, and blocked merges on a failing check for all 6 internal APIs.

**Impact:** Untested changes reaching the data pipelines dropped to zero and code review turnaround for the team fell from 2 days to same-day.
