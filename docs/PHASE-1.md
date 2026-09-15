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
- Added backend unit tests and GitHub Actions CI.
- Added `/health` for container health checks.
- Wired `SERVICE_ACCOUNT_TOKEN` into the backend container.
- Kept the current FastAPI + Django + Telegram + PostgreSQL architecture; no premature microservice split.

## Data model direction

`Content` is the canonical editorial object. A `ContentVersion` records every meaningful body revision. A `Publication` represents a delivery of content to one channel, so one piece of content can be published to multiple destinations without duplicating editorial data.

`Workspace` is the future tenancy boundary. `Channel` represents a concrete external destination such as a Telegram channel. `AuditLog` provides the foundation for traceability of human and AI actions.

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
```

## Next Phase 1 increments

The next implementation increments should add:

1. authenticated Workspace / Channel CRUD;
2. API endpoints for Content and ContentVersion;
3. Publication state machine with idempotency and retry semantics;
4. scheduler locking so multiple workers cannot publish the same job;
5. structured audit events around generation, editing, approval and publication.

AI strategy, content repurposing, multi-platform adapters and analytics remain Phase 2/3 concerns.
