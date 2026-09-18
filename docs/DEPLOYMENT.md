# Deployment

## Production topology

The supported deployment is Docker Compose with four services:

~~~text
PostgreSQL
   ↑
Backend ← Telegram
   ↑
Frontend
~~~

The backend is the source of truth for lifecycle, generation, variants, scheduling, and publication state. Telegram is the approval and operations adapter.

## Reverse proxy

The default Compose file binds the frontend to 127.0.0.1:3000. Put a TLS-terminating reverse proxy in front of it and set:

- WEBAPP_URL=https://your-host.example
- FRONTEND_PUBLIC_URL=https://your-host.example
- FRONTEND_HOST=your-host.example

Telegram WebApps require a valid public HTTPS origin.

## Startup and migrations

The backend waits for a healthy PostgreSQL service, runs alembic upgrade head, and only then starts Uvicorn. Never run ORM create_all() as a production schema-management mechanism.

The frontend runs its Django migrations from its entrypoint.

## Upgrade procedure

1. Create and verify a PostgreSQL backup.
2. Pull the new application revision.
3. Review release notes and migration changes.
4. Run docker compose up -d --build.
5. Confirm docker compose ps reports healthy/started services.
6. Check /health/ready.
7. Check Telegram /status.
8. Verify the Web UI and one non-destructive content/profile operation.
9. Monitor logs for failed migrations, provider errors, or notification retries.

## Rollback

Application rollback is version-dependent when database migrations are involved. Do not blindly downgrade production migrations. Restore the database backup and deploy the previously known-good application version when a migration rollback is unsafe.

## Backups

At minimum, take a PostgreSQL backup before every release that changes the schema. Keep backups outside the PostgreSQL container volume and periodically test restoration.
