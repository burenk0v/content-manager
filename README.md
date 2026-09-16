# content-manager

Content Manager is a Docker-based project with three main services for managing content schedules, topics, and Telegram bot integration.

## Overview

This system provides:

- **REST API** (FastAPI backend) for content management with scheduled posting
- **Admin Dashboard** (Django frontend) for UI management
- **Telegram Bot** (Aiogram) for admin commands and scheduled publishing
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
- **Key endpoints**:
  - `GET /` — service status
  - `GET /health/db` — database connectivity check
  - `GET /docs` — Swagger API documentation
  - `/content/*` — content management endpoints
- **Features**:
  - SQLAlchemy ORM with PostgreSQL
  - Content draft and schedule management
  - Topic AI generation
  - Authentication via `SERVICE_ACCOUNT_TOKEN`

#### Frontend (Django)

- **Port**: 8443 (HTTPS)
- **Pages**:
  - Dashboard — backend and database health overview
  - Dashboard — Docker container statuses and restart actions
  - Topics — view and delete AI-generated topics
  - Schedules — create, edit, delete publication schedules
  - Drafts — manage content drafts
  - Telegram Settings — per-user Telegram/OpenAI config values
- **Features**:
  - Multi-language support (Russian, English, Spanish)
  - Service-to-backend authentication
  - Schedule timezone conversion
  - Per-user Telegram settings stored in UI database
  - Docker container status and restart controls

#### Telegram Bot (Aiogram)

- **Features**:
  - `/start` — welcome message with WebApp button
  - `/ask <prompt>` — AI-generated content via OpenAI
  - Admin commands for manual triggers
  - Automatic schedule checking and publishing
  - Fetches drafts and schedules from backend
- **Integration**: Uses `SERVICE_ACCOUNT_TOKEN` for backend authentication

#### Database (PostgreSQL)

- **Port**: 5432
- **Health check**: Validates readiness every 10 seconds
- **Persistence**: Data stored in Docker volume `postgres_data`

## Environment Variables

Required configuration:

| Variable | Default | Description |
|----------|---------|-------------|
| `DB_USER` | `postgres` | PostgreSQL username |
| `DB_PASSWORD` | `postgres` | PostgreSQL password |
| `DB_NAME` | `content_manager` | Database name |
| `SERVICE_ACCOUNT_TOKEN` | — | Backend authentication token |
| `SECRET_KEY` | — | Django/backend secret key |
| `BOT_TOKEN` | — | Used as initial value for per-user UI Telegram settings |
| `ADMINS` | — | Used as initial value for per-user UI Telegram settings |
| `OPENAI_API_KEY` | — | Used as initial value for per-user UI Telegram settings |
| `WEBAPP_URL` | `https://example.com` | Used as initial value for per-user UI Telegram settings |
| `SCHEDULE_CHECK_INTERVAL_SECONDS` | `10` | Used as initial value for per-user UI Telegram settings |
| `PUBLICATION_WORKER_ID` | `telegram:<hostname>` | Stable worker identity used for publication leases |
| `PUBLICATION_POLL_INTERVAL_SECONDS` | `5` | Publication queue polling interval |
| `PUBLICATION_LEASE_HEARTBEAT_INTERVAL_SECONDS` | `60` | Publication lease heartbeat interval |
| `PUBLICATION_RECONCILIATION_POLL_INTERVAL_SECONDS` | `30` | Unknown-provider reconciliation polling interval |
| `PUBLICATION_LEASE_TIMEOUT_SECONDS` | `900` | Backend lease expiry window |
| `PUBLICATION_MAX_ATTEMPTS` | `5` | Maximum publication attempts |
| `PUBLICATION_RETRY_DELAY_SECONDS` | `60` | Initial retry delay; exponential backoff is applied |
| `PUBLICATION_RETRY_MAX_DELAY_SECONDS` | `3600` | Maximum retry delay |

## Supported Languages

- Russian (`ru`)
- English (`en`)
- Spanish (`es`)

## Getting Started

### Prerequisites

- Docker and Docker Compose
- Environment variables configured in `.env`

### Run Locally

```bash
docker compose up --build
```

Services will be available at:

- **Frontend**: https://localhost:8443
- **Backend API**: http://localhost:8000
- **Database**: localhost:5432

### View Logs

```bash
# All services
docker compose logs -f

# Specific service
docker compose logs -f telegram
docker compose logs -f backend
docker compose logs -f frontend
```

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
- **Publication Identity**: Each publication has a provider operation key separate from its database idempotency key
- **Provider Safety**: Ambiguous provider outcomes never trigger an automatic blind replay
