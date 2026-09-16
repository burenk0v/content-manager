# ADR 0005 — Architecture freeze

## Status

Accepted

## Context

The project has completed the architectural work needed for the current modular-monolith shape: application services own use cases, domain code owns pure business rules, providers are isolated behind contracts, persistence owns durable state, and operational/security concerns are explicit.

The next risk is architectural drift: a new feature can accidentally introduce a second implementation path, couple domain code to infrastructure, or bypass the established service/provider boundaries.

## Decision

Freeze the current dependency direction and capability ownership.

New product work must:

1. extend an existing capability owner when the behavior belongs to an existing domain;
2. enter through an application service for cross-layer use cases;
3. keep domain rules independent of FastAPI, SQLAlchemy sessions, provider SDKs, and transport modules;
4. access external systems through provider contracts/adapters;
5. use the existing persistence model and transaction boundaries instead of creating parallel state stores;
6. add an ADR when a new architectural boundary, persistence mechanism, provider contract, or cross-module dependency is required.

Architecture checks are part of CI. A failing boundary check is treated as an architectural regression, not as optional lint.

## Consequences

The repository can now evolve primarily through product features without reopening the basic layering decisions. Architectural changes remain possible, but they require an explicit reason, ownership, dependency direction, and migration plan.

This ADR does not prohibit refactoring. It prohibits silent architectural drift and duplicate paths for the same business operation.
