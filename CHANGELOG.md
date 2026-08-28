# Changelog

All notable changes to ServiceFlow API are documented in this file. The format is based on
[Keep a Changelog](https://keepachangelog.com/en/1.1.0/), and the project follows
[Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [Unreleased]

No changes yet.

## [1.0.0] - 2026-08-28

### Added

- Email-based JWT authentication with requester, agent, and admin roles.
- Ticket creation, assignment, take ownership, explicit workflow transitions, comments, filters,
  metrics, and append-only audit history.
- Persisted first-response and resolution SLA policies, deadlines, breach tracking, and periodic
  idempotent Celery checks.
- Validated multipart attachments with streaming SHA-256, private S3-compatible storage, and
  temporary authorized downloads.
- Redis/Celery asynchronous processing, structured JSON logs, request correlation, health checks,
  production settings, Docker Compose, OpenAPI, and GitHub Actions.

### Security

- Role and object-level authorization with requester queryset isolation.
- Redis-backed global, authentication, registration, and upload throttling.
- Private object storage, UUID keys, file allowlists, expiring signed URLs, and sanitized errors.
- Non-root runtime image, deployment checks, and dependency vulnerability auditing.

### Performance

- Related-object loading and attachment-count annotation for ticket lists.
- Composite status/priority ordering indexes and deadline indexes for SLA candidates.
- Query-budget regression coverage, PostgreSQL `EXPLAIN ANALYZE` review, deterministic performance
  seed, and reproducible Locust workload.

[Unreleased]: https://github.com/ldmrtnll-arch/serviceflow-api/compare/v1.0.0...HEAD
[1.0.0]: https://github.com/ldmrtnll-arch/serviceflow-api/releases/tag/v1.0.0
