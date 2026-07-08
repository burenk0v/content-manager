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
  - Topics — view and delete AI-generated topics
  - Schedules — create, edit, delete publication schedules
  - Drafts — manage content drafts
- **Features**:
  - Multi-language support (Russian, English, Spanish)
  - Service-to-backend authentication
  - Schedule timezone conversion

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
| `BOT_TOKEN` | — | Telegram bot token |
| `ADMINS` | — | Comma-separated Telegram admin IDs |
| `OPENAI_API_KEY` | — | OpenAI API key |
| `WEBAPP_URL` | `https://example.com` | Public URL for WebApp |
| `SCHEDULE_CHECK_INTERVAL_SECONDS` | `10` | Bot schedule check interval |

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

## Key Implementation Notes

- **Topics**: AI-generated topics can only be viewed and deleted via UI; creation is automated
- **Schedules**: Interval schedules use `last_run` as anchor for due checks; inactive schedules have `next_run = null`
- **Timezone**: Schedule timezone is persisted in backend and used for display/edit conversions
- **Draft Publishing**: Handles race conditions by reloading topics on `IntegrityError` during publish
- **Service Authentication**: All inter-service communication uses `SERVICE_ACCOUNT_TOKEN`
