# Troubleshooting

## Backend is unhealthy

Check:

~~~bash
docker compose ps
docker compose logs --tail=200 database
docker compose logs --tail=200 backend
curl http://127.0.0.1:8000/health/ready
~~~

If PostgreSQL is unavailable, fix the database/container/network issue first. The backend intentionally reports readiness failure until the database is reachable.

## Telegram bot starts but approvals do not arrive

Check:

- BOT_TOKEN is valid;
- ADMINS contains the intended Telegram IDs;
- SERVICE_ACCOUNT_TOKEN matches the backend;
- BACKEND_API_URL is reachable from the Telegram container;
- Telegram service logs show notification retry or backend errors.

Pending approval notifications are durable, so a service restart should not require regenerating the content.

## Generation is not happening

Check:

1. the Content Profile is active and due;
2. the scheduler is running;
3. the profile can be claimed;
4. the backend can reach the configured AI provider;
5. OPENAI_API_KEY and OPENAI_MODEL are valid;
6. recent GenerationRuns for the profile/content are not stuck in running.

An abandoned run can be recovered by the scheduler's stale-generation recovery path.

## Generation returns conflict

HTTP 409 means another active generation owns the content. This is intentional concurrency protection. Wait for that run to finish or become stale and recover; do not start parallel manual requests against the same content.

## Publication is stuck

Inspect the publication state and worker logs. A processing record should have a lease heartbeat. An ambiguous/unknown outcome must be reconciled before any manual retry that could duplicate an external side effect.

## WebApp does not open in Telegram

Verify that WEBAPP_URL is a publicly reachable HTTPS URL and matches the origin configured for the frontend. Check the reverse proxy certificate and forwarding configuration.

## Lost data after restart

Do not use docker compose down -v. Persistent application state lives in the PostgreSQL Docker volume. If the volume was deleted, restore the latest PostgreSQL backup.
