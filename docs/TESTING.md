# Testing

The repository uses automated backend, frontend, and Telegram test suites plus architecture and migration checks.

## Backend

From backend/:

~~~bash
pip install -r src/requirements.txt
pytest -q
~~~

Migration tests bootstrap a fresh PostgreSQL database to the current Alembic head and verify the resulting schema and indexes.

## Frontend and Telegram

Install each service's requirements from its src/requirements.txt and run its pytest suite from the corresponding service directory.

## Runtime coverage

The critical self-hosted flow should remain covered by tests for:

- durable GenerationRun creation and failure persistence;
- ContentVersion creation on successful generation;
- profile claim/concurrency behavior;
- stale generation recovery;
- database-level active-generation uniqueness;
- Telegram approval notification delivery and retry;
- publication claiming, leases, retries, and reconciliation;
- lifecycle state transitions;
- migration bootstrap/downgrade behavior.

## Release gate

Before merging a release candidate:

1. Run the complete CI suite.
2. Confirm all migration tests pass against a fresh database.
3. Build all Docker images.
4. Start the Compose stack with a clean PostgreSQL volume in an isolated environment.
5. Verify readiness and service startup.
6. Exercise one end-to-end profile generation → approval → scheduled publication → worker completion flow.
7. Verify restart recovery.
8. Review the migration chain for a single current Alembic head.\n9. Confirm service authentication rejects missing/invalid tokens and Telegram handlers reject non-admin users.

A green unit test suite alone is not sufficient evidence of a production-ready deployment.
