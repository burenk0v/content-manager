from __future__ import annotations

from datetime import datetime, timedelta, timezone
import os
import logging
import threading
import time
import uuid
from concurrent.futures import ThreadPoolExecutor

from sqlalchemy import or_, update
from sqlalchemy.orm import Session

from src.app.audit import audit
from src.app.db import SessionLocal
from src.app.models import ContentProfile, GenerationRun
from src.app.services.generation_service import (
    GenerationConflict,
    GenerationProviderFailure,
    generate_profile_content,
)
from src.app.services.profile_schedule_service import is_profile_ready


DEFAULT_SCHEDULER_INTERVAL_SECONDS = 15
DEFAULT_SCHEDULER_LEASE_TIMEOUT_SECONDS = 900


def _int_env(name: str, default: int, minimum: int, maximum: int) -> int:
    try:
        value = int(os.environ.get(name, str(default)))
    except ValueError:
        value = default
    return max(minimum, min(value, maximum))


def scheduler_interval_seconds() -> int:
    return _int_env("SCHEDULER_INTERVAL_SECONDS", DEFAULT_SCHEDULER_INTERVAL_SECONDS, 1, 3600)


def scheduler_max_concurrent_generations() -> int:
    return _int_env("MAX_CONCURRENT_GENERATIONS", 2, 1, 16)


def scheduler_lease_timeout_seconds() -> int:
    return _int_env(
        "SCHEDULER_LEASE_TIMEOUT_SECONDS",
        DEFAULT_SCHEDULER_LEASE_TIMEOUT_SECONDS,
        60,
        86400,
    )


def recover_stale_scheduler_leases(db: Session) -> int:
    now = datetime.utcnow()
    cutoff = now - timedelta(seconds=scheduler_lease_timeout_seconds())
    stale = (
        db.query(ContentProfile)
        .filter(
            ContentProfile.scheduler_lease_token.is_not(None),
            or_(
                ContentProfile.scheduler_lease_heartbeat_at.is_(None),
                ContentProfile.scheduler_lease_heartbeat_at < cutoff,
            ),
        )
        .all()
    )
    recovered = 0
    for profile in stale:
        result = db.execute(
            update(ContentProfile)
            .where(
                ContentProfile.id == profile.id,
                ContentProfile.scheduler_lease_token.is_not(None),
                or_(
                    ContentProfile.scheduler_lease_heartbeat_at.is_(None),
                    ContentProfile.scheduler_lease_heartbeat_at < cutoff,
                ),
            )
            .values(
                scheduler_lease_token=None,
                scheduler_lease_heartbeat_at=None,
                regeneration_requested=True,
                updated_at=now,
            )
            .execution_options(synchronize_session=False)
        )
        if result.rowcount != 1:
            continue
        audit(
            db,
            profile.workspace_id,
            "content_profile",
            profile.id,
            "scheduler_lease_recovered",
            event_type="content_profile.scheduler_lease_recovered",
        )
        recovered += 1
    if recovered:
        db.commit()
    return recovered


def _has_active_generation(db: Session, profile_id: int) -> bool:
    return (
        db.query(GenerationRun.id)
        .join(GenerationRun.content)
        .filter(
            GenerationRun.status == "running",
            GenerationRun.content.has(profile_id=profile_id),
        )
        .first()
        is not None
    )


def claim_due_profile(db: Session, profile_id: int) -> str | None:
    profile = (
        db.query(ContentProfile)
        .filter(ContentProfile.id == profile_id)
        .with_for_update()
        .first()
    )
    if not profile or not profile.is_active or profile.scheduler_lease_token:
        db.rollback()
        return None
    now_utc = datetime.utcnow().replace(tzinfo=timezone.utc)
    if _has_active_generation(db, profile.id):
        db.rollback()
        return None
    if not is_profile_ready(profile, now_utc):
        db.rollback()
        return None

    token = uuid.uuid4().hex
    now = datetime.utcnow()
    profile.scheduler_lease_token = token
    profile.scheduler_lease_heartbeat_at = now
    profile.updated_at = now
    audit(
        db,
        profile.workspace_id,
        "content_profile",
        profile.id,
        "scheduler_claimed",
        event_type="content_profile.scheduler_claimed",
    )
    db.commit()
    return token


def _heartbeat(profile_id: int, token: str, stop_event: threading.Event) -> None:
    interval = max(5.0, min(scheduler_lease_timeout_seconds() / 3.0, 60.0))
    while not stop_event.wait(interval):
        heartbeat_db = SessionLocal()
        try:
            result = heartbeat_db.execute(
                update(ContentProfile)
                .where(
                    ContentProfile.id == profile_id,
                    ContentProfile.scheduler_lease_token == token,
                )
                .values(scheduler_lease_heartbeat_at=datetime.utcnow())
                .execution_options(synchronize_session=False)
            )
            if result.rowcount != 1:
                heartbeat_db.rollback()
                return
            heartbeat_db.commit()
        except Exception:
            heartbeat_db.rollback()
        finally:
            heartbeat_db.close()


def _finish_lease(profile_id: int, token: str, *, success: bool) -> None:
    db = SessionLocal()
    try:
        now = datetime.utcnow()
        profile = (
            db.query(ContentProfile)
            .filter(
                ContentProfile.id == profile_id,
                ContentProfile.scheduler_lease_token == token,
            )
            .with_for_update()
            .first()
        )
        if profile is None:
            db.rollback()
            return
        profile.scheduler_lease_token = None
        profile.scheduler_lease_heartbeat_at = None
        profile.updated_at = now
        if success:
            profile.last_run = now
            profile.regeneration_requested = False
            action = "scheduler_completed"
            event_type = "content_profile.scheduler_completed"
        else:
            profile.regeneration_requested = True
            action = "scheduler_failed"
            event_type = "content_profile.scheduler_failed"
        audit(
            db,
            profile.workspace_id,
            "content_profile",
            profile.id,
            action,
            event_type=event_type,
        )
        db.commit()
    finally:
        db.close()


def run_profile(profile_id: int, token: str) -> None:
    stop_event = threading.Event()
    heartbeat_thread = threading.Thread(
        target=_heartbeat,
        args=(profile_id, token, stop_event),
        name=f"scheduler-heartbeat-{profile_id}",
        daemon=True,
    )
    heartbeat_thread.start()
    success = False
    db = SessionLocal()
    try:
        generate_profile_content(
            db,
            profile_id,
            scheduler_lease_token=token,
        )
        db.commit()
        success = True
    except (GenerationConflict, GenerationProviderFailure):
        db.rollback()
    except Exception:
        db.rollback()
    finally:
        db.close()
        stop_event.set()
        heartbeat_thread.join(timeout=2.0)
        _finish_lease(profile_id, token, success=success)


def scheduler_tick() -> int:
    db = SessionLocal()
    try:
        recover_stale_scheduler_leases(db)
        profiles = (
            db.query(ContentProfile.id)
            .filter(ContentProfile.is_active.is_(True))
            .order_by(ContentProfile.created_at.asc(), ContentProfile.id.asc())
            .all()
        )
    finally:
        db.close()

    claimed = 0
    jobs: list[tuple[int, str]] = []
    max_concurrent = scheduler_max_concurrent_generations()
    for (profile_id,) in profiles:
        if len(jobs) >= max_concurrent:
            break
        claim_db = SessionLocal()
        try:
            token = claim_due_profile(claim_db, profile_id)
        except Exception:
            claim_db.rollback()
            token = None
            logging.getLogger(__name__).exception("Failed to claim scheduler profile %s", profile_id)
        finally:
            claim_db.close()
        if token:
            jobs.append((profile_id, token))

    if not jobs:
        return 0

    with ThreadPoolExecutor(max_workers=len(jobs), thread_name_prefix="autonomous-generation") as executor:
        futures = [executor.submit(run_profile, profile_id, token) for profile_id, token in jobs]
        for future in futures:
            try:
                future.result()
            except Exception:
                logging.getLogger(__name__).exception("Autonomous scheduler worker failed")
    return len(jobs)


def run_forever() -> None:
    logger = logging.getLogger(__name__)
    while True:
        try:
            scheduler_tick()
        except Exception:
            logger.exception("Autonomous scheduler tick failed")
        time.sleep(scheduler_interval_seconds())


if __name__ == "__main__":
    run_forever()
