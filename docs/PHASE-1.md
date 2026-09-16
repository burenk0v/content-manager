# Phase 1 — production foundation

Phase 1 establishes the persistence and delivery foundation for the future AI-native content operations platform.

## What changed

- Added Alembic as the schema bootstrap mechanism; the repository supports a clean database created from the current schema only.
- Added a normalized content lifecycle model:
  - `User`
  - `Workspace`
  - `Channel`
  - `Content`
  - `ContentVersion`
  - `Publication`
  - `PublicationOperation`
  - `AuditLog`
- Added an explicit `Content` state machine: `draft -> review -> approved -> scheduled -> publishing -> published -> archived`, with controlled recovery paths through `draft` / `failed`.
- Added API endpoints to inspect allowed content transitions and perform a validated state transition.
- Removed the legacy Topic / Prompt / Schedule / PostDraft domain and its router. It is no longer part of the application contract.
- Replaced the migration history with a single `0001_initial` schema representing the current model. There is intentionally no upgrade path from legacy databases.
- Added backend and Telegram worker tests plus GitHub Actions CI.
- Added `/health` for container health checks.
- Wired `SERVICE_ACCOUNT_TOKEN` into the backend container.
- Added an explicit Telegram publication worker with atomic DB claims, stale-claim recovery, retry handling and provider-aware publication operations.
- Telegram publications are formatted and split into safe chunks when the rendered message is too large for Telegram's message limit.
- Added provider outcome reconciliation so an ambiguous external delivery is never blindly replayed.
- Kept the current FastAPI + Django + Telegram + PostgreSQL architecture; no premature microservice split.

## Data model direction

`Content` is the canonical editorial object. A `ContentVersion` records every meaningful body revision. A `Publication` represents a delivery of content to one channel, so one piece of content can be published to multiple destinations without duplicating editorial data.

`PublicationOperation` is the provider-facing delivery identity for a publication. Its `operation_key` is deliberately separate from the internal `Publication.idempotency_key` and is reused across retry attempts. This gives adapters a stable external operation identity without coupling provider semantics to database record creation.

`Workspace` is the future tenancy boundary. `Channel` represents a concrete external destination such as a Telegram channel. `AuditLog` provides the foundation for traceability of human and AI actions.

## Content state machine

The state machine is intentionally explicit rather than allowing arbitrary string updates:

```text
draft -> review -> approved -> scheduled -> publishing -> published -> archived
  ^       |          |            |             |
  |       +----------+------------+             +-> failed -> scheduled
  +-----------------------------------------------+
```

The API rejects invalid transitions with `409 Conflict`. This creates a stable contract for future Django UI, AI approval flows and provider workers.

## Publication delivery semantics

The publication queue uses an atomic `scheduled -> processing` claim so concurrent workers cannot normally process the same database job at the same time. Each processing claim has a unique lease token and heartbeat. Failed jobs can be rescheduled and stale processing claims can be recovered.

External delivery is intentionally **at-least-once**, not mathematically exactly-once. If a provider accepts a message and the worker crashes before the backend records `published`, the outcome can be unknown. `PublicationOperation` records that provider-facing operation separately from the internal publication idempotency key, allowing adapters with native idempotency to reuse the same operation key safely across retries.

For providers without idempotency (currently Telegram), an ambiguous network failure is persisted as `PublicationOperation.status = unknown` and the publication becomes terminally `failed` until reconciliation resolves the external outcome. Stale worker recovery treats an in-flight provider operation as unknown rather than automatically replaying it.

The provider-agnostic reconciliation endpoint accepts two explicit outcomes:

- `published` — record the provider's external identifier and close the publication as published;
- `retry` — explicitly confirm that no external delivery occurred and make the publication eligible for another processing attempt.

A future provider adapter can automate this decision by querying provider-side delivery state where the platform exposes a reliable lookup mechanism. The backend remains authoritative over the resulting publication state.

Telegram content is normalized to the supported HTML subset. Oversized rendered content is converted to conservative plain-text chunks before sending, avoiding a provider-side message-size failure.

## Database bootstrap

This private project intentionally supports **fresh installation only**. Existing databases are disposable and are not migrated between schema generations.

For a clean deployment, start with an empty database and run:

```bash
alembic upgrade head
```

The current schema is represented by one migration: `0001_initial`.

To run the bootstrap manually from the backend directory:

```bash
export DATABASE_URL='postgresql://user:password@localhost:5432/content_manager'
alembic upgrade head
```

If the schema changes during development, update the current model and replace/regenerate the single initial schema as part of the same clean-install workflow. Do not add compatibility migrations for discarded application versions.

## Test workflow

From `backend/`:

```bash
pip install -r src/requirements.txt
pytest -q
alembic upgrade head
```

The migration test creates an empty database and verifies that the current schema bootstraps successfully and that legacy tables are absent.

From `telegram/`:

```bash
pip install -r src/requirements.txt pytest pytest-asyncio
PYTHONPATH=src:. pytest -q
python -m compileall -q src
```

## Next implementation increments

1. add provider-specific idempotency/reconciliation implementations for adapters that support them;
2. make `ContentVersion` the canonical write path for human and AI edits;
3. add structured audit events for generation, editing, approval and provider reconciliation;
4. replace service-token-only lifecycle endpoints with authenticated workspace-scoped API access.

AI strategy, content repurposing, multi-platform adapters and analytics remain Phase 2/3 concerns.
