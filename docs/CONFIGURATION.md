# Configuration

Configuration is supplied through .env and passed to the services by Docker Compose. Never commit production secrets.

## Core settings

| Variable | Required | Purpose |
|---|---|---|
| DB_USER | yes | PostgreSQL user |
| DB_PASSWORD | yes | PostgreSQL password |
| DB_NAME | yes | PostgreSQL database |
| BACKEND_SECRET_KEY | yes | Backend application secret |
| SERVICE_ACCOUNT_TOKEN | yes | Internal service authentication for general backend clients |
| PUBLICATION_WORKER_TOKEN | yes | Dedicated authentication token for publication worker endpoints |
| FRONTEND_SECRET_KEY | yes | Django secret |
| ADMIN_USERNAME | yes | Initial Web operator |
| ADMIN_PASSWORD | yes | Initial Web operator password |
| ADMIN_EMAIL | yes | Initial Web operator email |
| BOT_TOKEN | yes | Telegram bot token |
| ADMINS | yes | Telegram administrator IDs |
| TELEGRAM_CALLBACK_SECRET | yes | HMAC secret for Telegram approval actions |
| WEBAPP_URL | yes | Public HTTPS Telegram WebApp URL |
| FRONTEND_PUBLIC_URL | yes | Public HTTPS frontend origin |
| OPENAI_API_KEY | yes | Current AI provider credential |
| OPENAI_MODEL | no | AI model, default gpt-4o-mini |

## AI runtime

- AI_GENERATION_PROVIDER selects the backend generation provider.
- AI_TRANSFORMATION_PROVIDER selects the channel transformation provider.
- GENERATION_LEASE_TIMEOUT_SECONDS controls recovery of abandoned generation runs. The runtime clamps this value to 60 seconds through 24 hours; default is 900 seconds. Active generation runs heartbeat from a separate DB session while the provider call is in progress.
- The current production implementation uses OpenAI. Provider selection is application-owned; Telegram does not call the AI SDK for autonomous generation.

## Scheduling and publication

- SCHEDULE_CHECK_INTERVAL_SECONDS controls profile schedule polling.
- PUBLICATION_WORKER_ID identifies the publication worker.
- PUBLICATION_POLL_INTERVAL_SECONDS controls publication queue polling.
- PUBLICATION_LEASE_HEARTBEAT_INTERVAL_SECONDS controls publication lease heartbeats.
- PUBLICATION_RECONCILIATION_POLL_INTERVAL_SECONDS controls ambiguous-outcome reconciliation polling.
- PUBLICATION_LEASE_TIMEOUT_SECONDS controls publication lease expiry.
- PUBLICATION_MAX_ATTEMPTS, PUBLICATION_RETRY_DELAY_SECONDS, and PUBLICATION_RETRY_MAX_DELAY_SECONDS control publication retries.

## Security

Use unique, high-entropy values for all application secrets and the service token. Restrict access to the Web UI and never expose the Docker socket to unrelated workloads. Rotate credentials if they are disclosed.

The frontend receives only read-only Docker API access for status inspection; it cannot restart containers or create/modify/remove Docker resources.
