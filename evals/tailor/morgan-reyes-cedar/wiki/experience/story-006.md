---
type: story
title: Terraform
job_title: Senior Backend Engineer
tags:
- Terraform
- AWS
- Docker
- Distributed Systems
- Backend
- Microservices
- PostgreSQL
- Code Review
- CI/CD
- Kafka
- GitHub Actions
story_type: SBI
timestamp: '2026-09-06T00:00:00+00:00'
---
# Terraform

**Situation:** Provisioning a new environment for a backend service at Northbeam meant an engineer clicking through the AWS console for 2 days, and configuration drifted between environments.

**Behavior:** Wrote Terraform modules covering the AWS networking, ECS task definitions, and IAM roles for a distributed systems footprint of 6 services and 3 databases, and put every change through a pull-request plan review.

**Impact:** New-environment setup dropped from 2 days to 2 hours and configuration drift between environments went to zero.
