# content-manager

<p align="center"><img src="docs/assets/content-manager-logo.svg" alt="Content Manager logo" width="180"></p>

<p align="center"><strong>Self-hosted AI content manager</strong><br>Autonomous generation · Telegram approvals · Automatic publishing</p>

Content Manager is a Docker-based project with three main services for managing content schedules, topics, AI-assisted content generation, and Telegram publishing.

## Overview

This system provides:

- **REST API** (FastAPI backend) for content management, AI generation, channel transformation, and scheduled posting
- **Admin Dashboard** (Django frontend) for UI management
- **Telegram Bot** (Aiogram) for approval and operator control
- **PostgreSQL Database** for persistent data storage

## Architecture

```
┌─────────────────┐      ┌──────────────┐
│    Frontend     │      │   Telegram   │
│    (Django)     │      │    Bot       │
└────────┬────────┘      └──────┬───────┘
         │                      │
         └──────────┬───────────┘
                    │
              ┌─────▼──────┐
              │  Backend   │
              │  (FastAPI) │
              └─────┬──────┘
                    │
              ┌─────▼─────────────┐
              │   PostgreSQL DB   │
              └───────────────────┘
```

### Service Details

#### Backend (FastAPI)

- **Port**: 8000
- **Health endpoints**: `GET /health/live` for process liveness and `GET /health/ready` for PostgreSQL readiness
- **Key endpoints**:
  - `GET /` — service status
  - `GET /health/db` — database connectivity check
  - `GET /docs` — Swagger API documentation
  - `/content/*` — content lifecycle, planning, publication, generation, and channel-variant endpoints
- **Features**:
  - SQLAlchemy ORM with PostgreSQL
  - Versioned content as the canonical content representation
  - AI generation with persisted generation runs
  - AI channel transformation with immutable variant history
  - Explicit content state machine and approval workflow
  - Provider-aware publication execution
  - Authentication via `SERVICE_ACCOUNT_TOKEN`

#### Frontend (Django)

- **Port**: 3000 on the host, mapped to port 8000 in the container (plain HTTP inside the deployment; terminate public HTTPS at a reverse proxy)
- **Pages**:
  - Dashboard — backend and database health overview
  - Topics — view and delete AI-generated topics
  - Schedules — create, edit, delete publication schedules
  - Drafts — manage content drafts
  - Telegram Settings — per-user Telegram/OpenAI config values
- **Features**:
  - Multi-language support (Russian, English, Spanish)
  - Service-to-backend authentication
  - Schedule timezone conversion
  - Per-user Telegram settings stored in UI database

#### Telegram Bot (Aiogram)

- **Features**:
  - `/start` — welcome message with WebApp button
  - Admin commands for manual triggers
  - Durable approval notifications and operator actions
  - Does not own scheduling or AI generation; the autonomous scheduler runs the backend generation pipeline
  - Publication worker orchestration
- **Integration**: Uses `SERVICE_ACCOUNT_TOKEN` for backend authentication

#### Database (PostgreSQL)

- **Health check**: Validates readiness every 10 seconds
- **Persistence**: Data stored in Docker volume `postgres_data`

## Self-hosted v1

The supported product flow is `Content Profile → autonomous AI generation → Telegram approval → publication worker`. Web is the configuration surface; Telegram is the approval and operations console.

For a fresh self-hosted deployment, copy `.env.example` to `.env`, replace all `CHANGE_ME_*` values, and run `docker compose up -d --build`. The backend applies Alembic migrations on startup and the frontend applies Django migrations before serving the UI. See `docs/GETTING_STARTED.md` for the first-run guide, `docs/SELF_HOSTING.md` for the deployment runbook, and `docs/RELEASE_CHECKLIST.md` before production releases.

The frontend no longer creates a hard-coded default admin account. Set `ADMIN_USERNAME`, `ADMIN_PASSWORD`, and `ADMIN_EMAIL` in `.env` for the initial operator account. The Compose deployment exposes the frontend at `127.0.0.1:3000` and the backend at `127.0.0.1:8000`; put a reverse proxy in front of the public HTTPS origin.

## Environment Variables

Required configuration:

| Variable | Default | Description |
|----------|---------|-------------|
| `DB_USER` | `content_manager` | PostgreSQL username |
| `DB_PASSWORD` | — | PostgreSQL password |
| `DB_NAME` | `content_manager` | Database name |
| `APP_ENV` | `production` | Application environment |\n| `BACKEND_SECRET_KEY` | — | Backend secret key |\n| `SERVICE_ACCOUNT_TOKEN` | — | Backend authentication token |
| `PUBLICATION_WORKER_TOKEN` | — | Dedicated authentication token for publication worker endpoints |
| `FRONTEND_SECRET_KEY` | — | Django frontend secret key |\n| `ADMIN_USERNAME` | — | Initial frontend admin username |\n| `ADMIN_PASSWORD` | — | Initial frontend admin password |\n| `ADMIN_EMAIL` | — | Initial frontend admin email |
| `BOT_TOKEN` | — | Used as initial value for per-user UI Telegram settings |
| `ADMINS` | — | Telegram administrator IDs |
| `TELEGRAM_CALLBACK_SECRET` | — | HMAC secret used to authenticate Telegram approval actions |
| `OPENAI_API_KEY` | — | OpenAI API key for backend AI generation and transformation |
| `OPENAI_MODEL` | `gpt-4o-mini` | Default model for backend AI generation and transformation |
| `AI_GENERATION_PROVIDER` | `openai` | Backend generation provider |
| `AI_TRANSFORMATION_PROVIDER` | `AI_GENERATION_PROVIDER` | Provider for channel-specific transformation |
| `REGISTRATION_ENABLED` | `false` | Whether public registration is enabled |\n| `WEBAPP_URL` | — | Public HTTPS URL opened from Telegram WebApp |\n| `FRONTEND_PUBLIC_URL` | — | Public HTTPS origin used by Django for CSRF validation |\n| `FRONTEND_HOST` | `127.0.0.1` | Hostname used by the frontend container |
| `SCHEDULE_CHECK_INTERVAL_SECONDS` | `10` | Used as initial value for per-user UI Telegram settings |
| `PUBLICATION_WORKER_ID` | `telegram:<hostname>` | Stable worker identity used for publication leases |
| `PUBLICATION_POLL_INTERVAL_SECONDS` | `5` | Publication queue polling interval |
| `PUBLICATION_LEASE_HEARTBEAT_INTERVAL_SECONDS` | `60` | Publication lease heartbeat interval |
| `PUBLICATION_RECONCILIATION_POLL_INTERVAL_SECONDS` | `30` | Unknown-provider reconciliation polling interval |
| `PUBLICATION_LEASE_TIMEOUT_SECONDS` | `900` | Backend lease expiry window |
| `GENERATION_LEASE_TIMEOUT_SECONDS` | `900` | Generation lease expiry window; active runs heartbeat during provider calls |
| `SCHEDULER_INTERVAL_SECONDS` | `15` | Autonomous scheduler polling interval |
| `SCHEDULER_LEASE_TIMEOUT_SECONDS` | `900` | Autonomous scheduler lease expiry window |
| `MAX_CONCURRENT_GENERATIONS` | `2` | Maximum concurrent autonomous generation workers |\n| `PYTHON_VALIDATOR_DIR` | `/var/lib/python-validator` | Shared directory for validator jobs |\n| `PYTHON_VALIDATOR_TIMEOUT_SECONDS` | `8` | Python validator execution timeout |
| `PUBLICATION_MAX_ATTEMPTS` | `5` | Maximum publication attempts |
| `PUBLICATION_RETRY_DELAY_SECONDS` | `60` | Initial retry delay; exponential backoff is applied |
| `PUBLICATION_RETRY_MAX_DELAY_SECONDS` | `3600` | Maximum retry delay |

## Documentation

- [Getting started](docs/GETTING_STARTED.md)
- [Configuration](docs/CONFIGURATION.md)
- [Deployment](docs/DEPLOYMENT.md)
- [Architecture](docs/ARCHITECTURE.md)
- [Operations](docs/OPERATIONS.md)
- [Testing](docs/TESTING.md)
- [Troubleshooting](docs/TROUBLESHOOTING.md)
- [Release checklist](docs/RELEASE_CHECKLIST.md)
- [Self-hosting](docs/SELF_HOSTING.md)

## Supported Languages

- Russian (`ru`)
- English (`en`)
- Spanish (`es`)

## AI Content Pipeline

AI generation is part of the content lifecycle rather than a separate draft system. A generation request creates a durable `GenerationRun` and, on success, a new `ContentVersion`.

The autonomous flow is:

`Content Profile → scheduler claim → GenerationRun → ContentVersion → draft → Telegram review → approved → scheduled → published`

Regeneration never overwrites an existing version. When generation happens from `review`, `approved`, or `scheduled`, the new version invalidates the previous approval and returns the content to `draft` for human review.

### Generation API

- `POST /content/contents/{content_id}/generate` — generate a new version
- `GET /content/contents/{content_id}/generations` — inspect generation history

The scheduler does not call an AI SDK directly. It claims a profile and invokes the backend generation service, which creates the durable `GenerationRun`, calls the configured provider through the backend provider contract, validates autonomous output, and persists a new `ContentVersion`. Provider failures are persisted as failed generation runs and the profile is re-queued for a later attempt. The current production provider is OpenAI.

## Channel Transformation

The canonical `ContentVersion` is channel-neutral. Before publication, the same source version can be transformed into channel-specific `ContentVariant` records.

A variant is immutable history for one source version and channel. Re-transforming creates the next variant version rather than overwriting the previous result. Variants start in `draft` so a human can preview and approve the channel-specific copy before publication wiring consumes it.

### Variant API

- `POST /content/contents/{content_id}/variants/{channel_id}/transform` — transform the latest content version, or an explicitly selected source version
- `GET /content/contents/{content_id}/variants` — inspect variants, optionally filtered by channel or source version

The transformer is provider-neutral. OpenAI is the current implementation and can be replaced without changing the variant data model or API contract. The target channel platform and content language are supplied to the transformer so channel-specific formatting can be applied without mutating canonical content.

## Publication Execution Model

A publication is claimed by exactly one worker using a processing token and lease heartbeat. Provider adapters are isolated behind a typed contract and selected through the provider registry.

Provider failures are classified into three operational outcomes:

1. **Success** — the provider returns an external identifier and the backend marks the publication as published.
2. **Permanent failure** — the input or provider configuration must change; the worker records a terminal failure without retrying.
3. **Ambiguous outcome** — the provider may have accepted the side effect but the worker cannot prove it; the publication is not blindly replayed and enters reconciliation.

The backend remains authoritative for retry limits, scheduling, leases, and publication state. Provider adapters must not implement their own retry policy.

Telegram currently supports publication but does not provide a safe provider-side reconciliation mechanism, so ambiguous Telegram deliveries remain available for manual reconciliation rather than being automatically duplicated.

## Key Implementation Notes

- **Topics**: AI-generated topics can only be viewed and deleted via UI; creation is automated
- **Schedules**: Interval schedules use `last_run` as anchor for due checks; inactive schedules have `next_run = null`
- **Timezone**: Schedule timezone is persisted in backend and used for display/edit conversions
- **Draft Publishing**: Handles race conditions by reloading topics on `IntegrityError` during publish
- **Service Authentication**: All inter-service communication uses `SERVICE_ACCOUNT_TOKEN`
- **Content Lifecycle**: Content status transitions are validated by a dedicated domain state machine
- **Content Versions**: Versions are immutable and publications pin the exact version they publish
- **Generation History**: Every AI generation attempt is persisted with provider, model, prompt, status, and resulting version
- **Channel Variants**: Channel transformations are versioned per source content version and channel; canonical content remains untouched
- **Publication Identity**: Each publication has a provider operation key separate from its database idempotency key
- **Provider Safety**: Ambiguous provider outcomes never trigger an automatic blind replay
