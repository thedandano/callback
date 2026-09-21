---
type: story
title: Terraform
job_title: Backend Engineer
tags:
- Terraform
- AWS
- Docker
- CI/CD
story_type: SBI
timestamp: '2026-09-06T00:00:00+00:00'
---
# Terraform

**Situation:** Each of the 12 checkout services at Acme Corp was deployed by hand to AWS ECS, and a new service took a week to reach production.

**Behavior:** Wrote reusable Terraform modules for the ECS task definitions, built the Docker images in GitHub Actions, and wired the plan output into every pull request.

**Impact:** A new service ships in one pull request and the release cycle dropped from two weeks to one day.
