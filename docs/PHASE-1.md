# Phase 1 — production foundation

Phase 1 establishes the persistence and delivery foundation for the future AI-native content operations platform.

## What changed

- Added Alembic migrations and moved schema management out of FastAPI startup.
- Added a normalized content lifecycle model:
  - `Workspace`
  - `Channel`
  - `Content`
  - `ContentVersion`
  - `Publication`
  - `AuditLog`
- Kept the existing Topic / Prompt / Schedule / PostDraft model intact for backward compatibility.
- Added a migration that can create the existing schema on a fresh database and add the legacy columns required by current deployments.
- Added backend and Telegram worker tests plus GitHub Actions CI.
- Added `/health` for container health checks.
- Wired `SERVICE_ACCOUNT_TOKEN` into the backend container.
- Added an explicit Telegram publication worker with atomic DB claims, stale-claim recovery, retry handling and idempotent publication jobs.
- Telegram publications are formatted and split into safe chunks when the rendered message is too large for Telegram's message limit.
- Kept the current FastAPI + Django + Telegram + PostgreSQL architecture; no premature microservice split.

## Data model direction

`Content` is the canonical editorial object. A `ContentVersion` records every meaningful body revision. A `Publication` represents a delivery of content to one channel, so one piece of content can be published to multiple destinations without duplicating editorial data.

`Workspace` is the future tenancy boundary. `Channel` represents a concrete external destination such as a Telegram channel. `AuditLog` provides the foundation for traceability of human and AI actions.

## Publication delivery semantics

The publication queue uses an atomic `scheduled -> processing` claim so concurrent workers cannot normally process the same database job at the same time. Failed jobs can be rescheduled and stale processing claims can be recovered.

External delivery is intentionally **at-least-once**, not mathematically exactly-once. If Telegram accepts a message and the worker crashes before the backend records `published`, the recovered job can be delivered again. The database idempotency key prevents duplicate publication records; it cannot make an external Telegram API call exactly-once. A future adapter layer can add provider-specific idempotency or reconciliation where supported.

Telegram content is normalized to the supported HTML subset. Oversized rendered content is converted to conservative plain-text chunks before sending, avoiding a provider-side message-size failure.

## Migration workflow

For a fresh deployment, the backend container runs:

```bash
alembic upgrade head
```

before starting Uvicorn.

For an existing database created by a pre-Alembic version, back up the database before deploying Phase 1. The `0001_phase1_foundation` migration is designed to preserve existing tables and add missing legacy columns, then create the Phase 1 tables.

To run migrations manually from the backend directory:

```bash
export DATABASE_URL='postgresql://user:password@localhost:5432/content_manager'
alembic upgrade head
```

## Test workflow

From `backend/`:

```bash
pip install -r src/requirements.txt
pytest -q
alembic upgrade head
```

From `telegram/`:

```bash
pip install -r src/requirements.txt pytest pytest-asyncio
PYTHONPATH=. pytest -q
python -m compileall -q src
```

## Next Phase 1 increments

The next implementation increments should add:

1. authenticated Workspace / Channel CRUD;
2. API endpoints for Content and ContentVersion;
3. stronger retry policy with exponential backoff and jitter;
4. migration tests for legacy database -> Phase 1 -> head;
5. provider adapter boundaries so Telegram delivery is isolated from the publication domain;
6. structured audit events around generation, editing, approval and publication.

AI strategy, content repurposing, multi-platform adapters and analytics remain Phase 2/3 concerns.
