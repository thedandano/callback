---
type: story
title: Docker
job_title: Senior Backend Engineer
tags:
- Docker
- AWS
- Terraform
- Backend
- Microservices
- Java
- Spring Boot
- Kafka
- CI/CD
- Code Review
- Distributed Systems
- PostgreSQL
story_type: SBI
timestamp: '2026-09-06T00:00:00+00:00'
---
# Docker

**Situation:** All 12 backend services deployed from a hand-maintained set of AWS EC2 AMIs, and a new service took 3 days to onboard because the AMI build was manual.

**Behavior:** Containerized all 12 services with Docker, standardized the base image, and moved deployment to AWS ECS with a shared Terraform module for the task definitions.

**Impact:** New-service onboarding dropped from 3 days to half a day and every service now runs the same base image.
