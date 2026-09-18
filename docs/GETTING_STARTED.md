# Getting started

This guide takes a new self-hosted installation from an empty checkout to the first approved publication.

## Prerequisites

- Docker Engine with Docker Compose v2.
- A Telegram bot token and at least one administrator Telegram user ID.
- An OpenAI API key for the current production AI provider.
- A public HTTPS origin for the Telegram WebApp.

No external application database is required: PostgreSQL is included in Compose.

## First installation

1. Copy .env.example to .env.
2. Replace every CHANGE_ME_* value with a strong secret or real integration value.
3. Set WEBAPP_URL and FRONTEND_PUBLIC_URL to the same public HTTPS origin.
4. Build and start the stack:

~~~bash
docker compose up -d --build
~~~

5. Verify service state:

~~~bash
docker compose ps
curl http://127.0.0.1:8000/health/ready
~~~

6. Open the Web UI through the configured HTTPS reverse proxy and sign in with ADMIN_USERNAME / ADMIN_PASSWORD.
7. Open **Content Profiles**. On a fresh installation, use **First-run setup** to create a workspace and add the Telegram channel (`@channel_username` or a negative numeric channel ID such as `-1001234567890`). The bot must already be an administrator of that channel with permission to post.
8. Create a Content Profile for that workspace/channel with language, niche, tone, format, editorial rules, timezone, and generation cadence. Keep **Active** enabled for autonomous generation.
9. Wait for the profile to become due, or use the Telegram `/generate <profile_id>` command for an immediate run.
10. Review the generated post in Telegram and approve, reject, or regenerate it. Approval creates the publication automatically; no second publication target or schedule setup is required.

## Expected first-run sequence

Workspace → Telegram Channel → Content Profile → GenerationRun → ContentVersion → review → approved → scheduled → publishing → published

A provider failure is persisted as a failed GenerationRun and the profile is eligible for a later autonomous attempt. A restart does not require recreating generation state.

## Stop and restart

~~~bash
docker compose down
docker compose up -d
~~~

Do not use docker compose down -v unless you intentionally want to delete the PostgreSQL volume and all persistent application data.
