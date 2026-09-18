# Release checklist

Use this checklist for every production release.

## Code and CI

- [ ] Release branch is based on current main.
- [ ] Backend, frontend, and Telegram CI are green.
- [ ] Architecture checks are green.
- [ ] Migration tests are green.
- [ ] No secrets or local database files are committed.
- [ ] README and operational documentation match the current runtime.

## Database

- [ ] Migration chain has exactly one current Alembic head.
- [ ] New migrations have upgrade and downgrade paths where supported.
- [ ] A PostgreSQL backup was completed before deployment.
- [ ] Restoration of a recent backup has been tested according to the deployment policy.

## Self-hosted deployment

- [ ] .env.example contains every required operator setting.
- [ ] Production .env uses unique strong secrets.
- [ ] Telegram bot token and administrator IDs are valid.
- [ ] Public HTTPS WebApp URL is configured.
- [ ] Reverse proxy is configured.
- [ ] Docker images build successfully.
- [ ] Compose starts PostgreSQL before backend and backend before dependent services.
- [ ] Backend readiness is healthy.
- [ ] Frontend and Telegram services are running.

## End-to-end validation

- [ ] A Content Profile can be created and claimed.
- [ ] A successful generation creates a GenerationRun and ContentVersion.
- [ ] A provider failure is persisted without losing the profile retry signal.
- [ ] Telegram receives the review notification.
- [ ] Approve, reject, and regenerate actions work.
- [ ] An approved version can be scheduled.
- [ ] Publication succeeds or enters the documented failure/reconciliation state.
- [ ] Restarting the backend/Telegram services does not lose pending work.
- [ ] Duplicate generation/publication is prevented by the runtime contracts.

## Rollback

- [ ] Previous application revision is known.
- [ ] Database backup location is recorded.
- [ ] Migration rollback strategy is understood for this release.
- [ ] Recovery owner and operational contact are known.
