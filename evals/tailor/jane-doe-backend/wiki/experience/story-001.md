---
type: story
title: FastAPI
job_title: Backend Engineer
tags:
- FastAPI
- PostgreSQL
- Python
- Observability
story_type: SBI
timestamp: '2026-09-06T00:00:00+00:00'
---
# FastAPI

**Situation:** Acme Corp's checkout API ran on a synchronous framework and p95 latency sat near 900ms during the 2M-order monthly peak.

**Behavior:** Rebuilt the service on FastAPI with PostgreSQL connection pooling, added Datadog dashboards for every endpoint, and load-tested each release against production traffic replays.

**Impact:** p95 latency fell 40% and the on-call pager went from 6 pages a week to 1.
