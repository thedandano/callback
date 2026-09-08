---
type: story
title: Spring Boot
job_title: Senior Backend Engineer
tags:
- Spring Boot
- Java
- Microservices
- Backend
- PostgreSQL
- Docker
- AWS
- Kafka
- Code Review
- CI/CD
- Distributed Systems
- GitHub Actions
story_type: SBI
timestamp: '2026-09-06T00:00:00+00:00'
---
# Spring Boot

**Situation:** Each new backend service at Northbeam took 2 weeks to bootstrap because there was no shared framework for auth, logging, or health checks.

**Behavior:** Built a Spring Boot starter library with shared auth, structured logging, and health-check endpoints, and rolled it out across 8 services.

**Impact:** New-service bootstrap time dropped from 2 weeks to 3 days, and every service now reports consistent health metrics.
