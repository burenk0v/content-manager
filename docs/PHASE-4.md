# Phase 4 — Observability, Security & Testing

## Goal

Make operational visibility, security boundaries, and regression protection first-class architectural concerns before the final architecture freeze.

## Scope

- request correlation and structured HTTP/publication logging;
- Prometheus-compatible application metrics;
- explicit liveness/readiness endpoints with database readiness checks;
- production-safe secret configuration (no insecure authentication fallback);
- audit/service endpoint hardening and bounded query parameters;
- focused tests for observability, health, security, and metrics;
- CI gates for formatting/type checks and the backend test suite.

## Non-goals

- introducing a distributed tracing stack;
- introducing a full external monitoring platform;
- redesigning the domain model;
- changing product behavior.

## Exit criteria

- every HTTP request has a correlation ID and emits a structured log event;
- publication lifecycle emits structured operational events;
- `/health/live` does not require dependencies and `/health/ready` verifies the database;
- production authentication cannot start with a known default JWT secret;
- metrics expose request and publication counters/durations without leaking credentials or content;
- tests cover the new operational/security contracts;
- CI runs tests plus static checks before migrations.
