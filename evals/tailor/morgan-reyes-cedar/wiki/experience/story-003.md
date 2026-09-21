---
type: story
title: Kafka
job_title: Senior Backend Engineer
tags:
- Kafka
- PostgreSQL
- Distributed Systems
- Microservices
- Backend
- Java
- Spring Boot
- AWS
- Docker
- Code Review
- CI/CD
- Redis
- Terraform
story_type: SBI
timestamp: '2026-09-06T00:00:00+00:00'
---
# Kafka

**Situation:** Order status updates were polled from PostgreSQL every 30 seconds by 5 downstream services, adding load and a 30-second lag to shipping notifications.

**Behavior:** Introduced a Kafka topic for order-status events, migrating the 5 downstream services from polling to event consumption with idempotent handlers.

**Impact:** Notification lag dropped from 30 seconds to under 2 seconds and PostgreSQL polling load fell 70%.
