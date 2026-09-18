# Self-hosting

Content Manager runs as a small Docker Compose deployment: PostgreSQL, Backend, Frontend, and Telegram.

## 1. Configure

Copy .env.example to .env and replace every CHANGE_ME_* value. Generate long random values for BACKEND_SECRET_KEY, SERVICE_ACCOUNT_TOKEN, PUBLICATION_WORKER_TOKEN, and FRONTEND_SECRET_KEY.

The Telegram bot token and ADMINS are required for the approval console. GENERATION_LEASE_TIMEOUT_SECONDS defaults to 900 seconds and controls stale generation recovery. WEBAPP_URL must be an HTTPS URL reachable by Telegram clients.

## 2. Start

Run `docker compose up -d --build`.

The backend waits for PostgreSQL, applies Alembic migrations, and then starts the API. The frontend applies Django migrations before serving the Web UI.

## 3. Verify

Run `docker compose ps`. The backend readiness endpoint is available at `/health/ready`. The Web UI is exposed on port 3000 by the default Compose configuration.

Open the Web UI and create or edit a Content Profile with its channel, language, niche, editorial rules, timezone, and cadence.

## 4. Operate

Telegram is the approval and operations console:

- `/status` — system/content status
- `/profiles` — autonomous profiles
- `/queue` — waiting approval
- `/generate <profile_id>` — manual generation
- `/web` — open Web configuration

Normal flow: Content Profile → AI generation → validation → Telegram approval → publication worker.

Approve, reject, or regenerate directly from the Telegram message.

## 5. Upgrades and backups

Back up PostgreSQL before upgrades. Use `bash scripts/backup_postgres.sh` and keep at least one copy outside the deployment host.

For an upgrade: back up the database, pull the new version, run `docker compose up -d --build`, verify `/health/ready` and `docker compose ps`, then inspect Telegram `/status`.

To restore a dump, stop application writers first, then run `bash scripts/restore_postgres.sh <dump>` and verify readiness before resuming workers.

## Public HTTPS / Telegram WebApp

The frontend container serves plain HTTP through Uvicorn on port 8000 and is bound to `127.0.0.1:3000` by the default Compose file. For a real Telegram WebApp, place a reverse proxy in front of it and terminate TLS there with a certificate valid for the public hostname.

Set both WEBAPP_URL and FRONTEND_PUBLIC_URL to the same public HTTPS origin, for example `https://content.example.com`. The reverse proxy should forward that origin to `http://127.0.0.1:3000`.

The frontend no longer has Docker write access. The Docker socket proxy is read-only at the API level and is used only for container status inspection. Keep the management interface behind trusted network controls and do not expose the Docker socket to unrelated containers.

## Approval notification recovery

Approval notifications are persisted as part of the content lifecycle. If the Telegram send fails or the Telegram service restarts, review items remain pending and the scheduler retries their notification. A notification claim expires after five minutes so an interrupted worker can recover it.
