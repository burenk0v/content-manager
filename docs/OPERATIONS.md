# Operations

## Health

Use the backend endpoints:

- /health/live — process is alive.
- /health/ready — process can reach PostgreSQL; returns HTTP 503 when the database is unavailable.
- /metrics — application metrics.
- /docs — interactive API documentation.

Useful commands:

~~~bash
docker compose ps
docker compose logs --tail=200 backend
docker compose logs --tail=200 telegram
docker compose logs --tail=200 frontend
~~~

## Database backups

Back up PostgreSQL before upgrades and on a regular schedule. The repository includes scripts that use the running Compose database container:

~~~bash
bash scripts/backup_postgres.sh
bash scripts/restore_postgres.sh backups/content-manager-YYYYMMDD-HHMMSS.dump
~~~

Backups are custom-format PostgreSQL dumps. Store them outside the deployment host as well; a Docker volume is not a backup.

After restoring, verify the backend readiness endpoint and Telegram `/status`. Never restore over the only copy of a production backup.

## Generation operations

A GenerationRun is durable state. For an abandoned run, the backend can recover stale runs through the service-protected recovery endpoint. The scheduler invokes recovery before claiming new due profiles.

Generation concurrency is protected twice:

1. application-level freshness checks;
2. a database uniqueness guard allowing only one running GenerationRun per content.

The persisted lease heartbeat is used to determine freshness, with created_at as the fallback for old records.

## Approval operations

Approval notifications are persisted and retried. A failed Telegram send does not discard the review item. A notification claim expires so an interrupted worker can retry it.

Approval actions must operate on the intended content/version. Regeneration creates a new immutable ContentVersion and returns content to human review rather than silently changing an already approved version.

## Publication operations

Publication execution uses a processing token and lease heartbeat. Outcomes are classified as success, permanent failure, or ambiguous outcome. Ambiguous provider outcomes are not blindly replayed; they enter reconciliation/manual handling according to the provider capabilities.

## Routine checks

After deployment, periodically verify:

- database backups are completing;
- /health/ready remains healthy;
- Telegram notification retries are not accumulating;
- GenerationRuns are not accumulating in running;
- publications are not accumulating in processing or unknown;
- provider credentials have not expired;
- disk space is sufficient for PostgreSQL and Docker.

## Incident rule

When a provider or database incident occurs, preserve durable state first. Inspect GenerationRuns, publications, and audit records before manually repeating an action. The system is designed to avoid blind duplicate generation/publication.
