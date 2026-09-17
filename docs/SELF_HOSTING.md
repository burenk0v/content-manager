# Self-hosting

Content Manager runs as a small Docker Compose deployment: PostgreSQL, Backend, Frontend, and Telegram.

## 1. Configure

Copy .env.example to .env and replace every CHANGE_ME_* value. Generate long random values for BACKEND_SECRET_KEY, SERVICE_ACCOUNT_TOKEN, and FRONTEND_SECRET_KEY.

The Telegram bot token and ADMINS are required for the approval console. WEBAPP_URL must be an HTTPS URL reachable by Telegram clients.

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

Back up PostgreSQL before upgrades. Database schema changes are managed only by Alembic; application startup does not call `create_all()`.

For an upgrade: back up the database, pull the new version, run `docker compose up -d --build`, verify `/health/ready` and `docker compose ps`, then inspect Telegram `/status`.
