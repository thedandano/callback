---
type: story
title: Redis
job_title: Senior Backend Engineer
tags:
- Redis
- PostgreSQL
- Backend
- Distributed Systems
- Microservices
- AWS
- Docker
- Kafka
- CI/CD
- Code Review
story_type: SBI
timestamp: '2026-09-06T00:00:00+00:00'
---
# Redis

**Situation:** The order database saw repeated reads of the same cart and pricing data, and PostgreSQL p95 read latency climbed to 900ms during Northbeam's peak shipping weeks.

**Behavior:** Added a Redis cache in front of the cart and pricing reads with a 5-minute TTL and a cache-invalidation hook on writes.

**Impact:** p95 read latency fell 45% and PostgreSQL CPU usage dropped 30% during the next peak week.
