# Phase 2 — Persistence & Concurrency

Phase 2 hardens the persistence layer so the existing domain/application flows remain safe when multiple API requests and publication workers operate concurrently.

## Database invariants

The database now enforces the invariants that must hold independently of application code:

- content lifecycle states are limited to the states defined by the domain state machine;
- publication and provider-operation states are explicit and bounded;
- generation runs have only `running`, `succeeded`, or `failed` states;
- version numbers are positive;
- publication/provider-operation attempt counters cannot be negative;
- existing unique keys remain the source of truth for idempotency and publication identity.

These constraints are mirrored in SQLAlchemy models and are introduced by Alembic migration `0004_persistence_guards`.

## Publication concurrency

Publication claiming and lease ownership remain database-atomic:

- a claim changes `scheduled → processing` only when the publication is still eligible;
- the worker receives a unique processing token;
- heartbeat, completion, and failure updates require the current worker/token and a non-expired lease;
- stale recovery uses a conditional update so a worker that has renewed its lease cannot be reclaimed accidentally;
- provider operation identity is separate from the database idempotency key and survives retry attempts;
- an unknown provider outcome is never converted into a blind automatic replay.

The application-level conditional updates already present in the publication service are therefore treated as concurrency boundaries rather than as best-effort checks.

## Queue indexes

Two composite indexes support the hot publication paths:

- `ix_publications_ready_queue` — scheduled/retry queue scans;
- `ix_publications_stale_processing` — stale lease recovery scans.

They are intentionally ordered around the state/time predicates used by the worker and recovery endpoints.

## Transaction rule

A command that changes persistent state must complete its database mutation, related audit records, and state synchronization in one transaction. External provider calls remain outside the database transaction; their result is persisted only through the publication lease/token protocol and provider-operation state.

Phase 2 does not introduce a generic transaction abstraction merely for indirection. The existing SQLAlchemy session is the transaction boundary, while the database constraints and conditional updates provide the concurrency guarantees that cannot safely live only in Python.
