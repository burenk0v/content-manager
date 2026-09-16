from datetime import datetime, timedelta
from typing import NamedTuple
import os
import uuid

from fastapi import HTTPException
from sqlalchemy import and_, or_, update
from sqlalchemy.orm import Session

from src.app.audit import audit
from src.app.models import Content, Publication
from src.app.observability import publication_event
from src.app.publication_state import sync_content_status

DEFAULT_LEASE_TIMEOUT_SECONDS = 900
MIN_LEASE_TIMEOUT_SECONDS = 60
MAX_LEASE_TIMEOUT_SECONDS = 86400
DEFAULT_MAX_ATTEMPTS = 5
DEFAULT_RETRY_DELAY_SECONDS = 60
DEFAULT_RETRY_MAX_DELAY_SECONDS = 3600


def config_int(name: str, default: int, minimum: int, maximum: int) -> int:
    raw = os.environ.get(name, str(default))
    try:
        value = int(raw)
    except ValueError:
        value = default
    return max(minimum, min(value, maximum))


def lease_timeout_seconds() -> int:
    return config_int("PUBLICATION_LEASE_TIMEOUT_SECONDS", DEFAULT_LEASE_TIMEOUT_SECONDS, MIN_LEASE_TIMEOUT_SECONDS, MAX_LEASE_TIMEOUT_SECONDS)


def lease_cutoff(now: datetime) -> datetime:
    return now - timedelta(seconds=lease_timeout_seconds())


def retry_max_attempts() -> int:
    return config_int("PUBLICATION_MAX_ATTEMPTS", DEFAULT_MAX_ATTEMPTS, 1, 20)


def retry_delay_seconds(attempt_count: int) -> int:
    base = config_int("PUBLICATION_RETRY_DELAY_SECONDS", DEFAULT_RETRY_DELAY_SECONDS, 1, 86400)
    cap = config_int("PUBLICATION_RETRY_MAX_DELAY_SECONDS", DEFAULT_RETRY_MAX_DELAY_SECONDS, base, 86400)
    return min(cap, base * (2 ** max(0, attempt_count - 1)))


def transition_content(db: Session, content: Content, target: str) -> None:
    if content.status == target:
        return
    from src.app.domain.content_state_machine import transition
    previous_status = content.status
    transition(previous_status, target)
    content.status = target
    content.updated_at = datetime.utcnow()
    audit(
        db,
        content.workspace_id,
        "content",
        content.id,
        "status_changed",
        event_type="content.status_changed",
        metadata={"from": previous_status, "to": target},
    )


class PublicationEvent(NamedTuple):
    event: str
    publication_id: int
    status: str
    worker_id: str | None = None
    attempt_count: int | None = None
    error: str | None = None


def recover_stale(db: Session) -> list[Publication]:
    now = datetime.utcnow()
    cutoff = lease_cutoff(now)
    stale_ids = [item.id for item in db.query(Publication.id).filter(
        Publication.status == "processing",
        or_(
            and_(Publication.lease_heartbeat_at.is_not(None), Publication.lease_heartbeat_at < cutoff),
            and_(Publication.lease_heartbeat_at.is_(None), Publication.processing_started_at.is_not(None), Publication.processing_started_at < cutoff),
        ),
    ).all()]
    recovered = []
    for publication_id in stale_ids:
        publication = db.query(Publication).filter(Publication.id == publication_id).first()
        if not publication:
            continue
        operation = publication.provider_operation
        outcome_unknown = operation is not None and operation.status == "processing"
        target_status = "failed" if outcome_unknown else "scheduled"
        error_message = (
            "Provider operation outcome is unknown after stale lease recovery"
            if outcome_unknown
            else "Recovered stale processing claim"
        )
        result = db.execute(update(Publication).where(
            Publication.id == publication_id,
            Publication.status == "processing",
            or_(
                and_(Publication.lease_heartbeat_at.is_not(None), Publication.lease_heartbeat_at < cutoff),
                and_(Publication.lease_heartbeat_at.is_(None), Publication.processing_started_at.is_not(None), Publication.processing_started_at < cutoff),
            ),
        ).values(
            status=target_status, next_attempt_at=None if outcome_unknown else now,
            processing_started_at=None, processing_token=None, lease_heartbeat_at=None, worker_id=None,
            error_message=error_message,
        ).execution_options(synchronize_session=False))
        if result.rowcount != 1:
            continue
        publication = db.query(Publication).populate_existing().filter(Publication.id == publication_id).first()
        if operation and operation.status == "processing":
            operation.status = "unknown"
            operation.last_error = error_message
            operation.updated_at = now
        sync_content_status(db, publication.content)
        audit(
            db,
            publication.channel.workspace_id,
            "publication",
            publication.id,
            "recovered",
            event_type="publication.recovered",
            metadata={"status": publication.status, "error_message": error_message},
        )
        recovered.append(publication)
    if recovered:
        db.commit()
        for publication in recovered:
            db.refresh(publication)
            publication_event("recovered", publication.id, status=publication.status, attempt_count=publication.attempt_count, error=publication.error_message)
    return recovered


def claim(db: Session, publication_id: int, worker_id: str) -> Publication:
    now = datetime.utcnow()
    processing_token = uuid.uuid4().hex
    eligible = and_(
        or_(Publication.scheduled_at.is_(None), Publication.scheduled_at <= now),
        or_(Publication.next_attempt_at.is_(None), Publication.next_attempt_at <= now),
    )
    result = db.execute(update(Publication).where(
        Publication.id == publication_id, Publication.status == "scheduled", eligible
    ).values(
        status="processing", processing_started_at=now, processing_token=processing_token,
        lease_heartbeat_at=now, worker_id=worker_id,
        attempt_count=Publication.attempt_count + 1, error_message=None,
    ).execution_options(synchronize_session=False))
    if result.rowcount != 1:
        db.rollback()
        publication = db.query(Publication).filter(Publication.id == publication_id).first()
        if not publication:
            raise HTTPException(404, "Publication not found")
        raise HTTPException(409, "Publication is not claimable")
    publication = db.query(Publication).populate_existing().filter(Publication.id == publication_id).first()
    operation = publication.provider_operation
    if operation is None:
        db.rollback()
        raise HTTPException(500, "Publication provider operation is missing")
    if operation.status == "unknown":
        db.rollback()
        raise HTTPException(409, "Provider operation outcome is unknown and requires reconciliation")
    operation.status = "processing"
    operation.attempt_count += 1
    operation.last_error = None
    operation.updated_at = now
    if publication.content.status != "publishing":
        transition_content(db, publication.content, "publishing")
    audit(
        db,
        publication.channel.workspace_id,
        "publication",
        publication.id,
        "claimed",
        event_type="publication.claimed",
        metadata={"worker_id": worker_id, "attempt_count": publication.attempt_count},
    )
    response = publication
    event = PublicationEvent("claimed", publication.id, publication.status, publication.worker_id, publication.attempt_count)
    db.commit()
    publication_event(event.event, event.publication_id, status=event.status, worker_id=event.worker_id, attempt_count=event.attempt_count)
    return response


def heartbeat(db: Session, publication_id: int, worker_id: str, processing_token: str) -> Publication:
    now = datetime.utcnow()
    result = db.execute(update(Publication).where(
        Publication.id == publication_id, Publication.status == "processing",
        Publication.worker_id == worker_id, Publication.processing_token == processing_token,
        Publication.lease_heartbeat_at >= lease_cutoff(now),
    ).values(lease_heartbeat_at=now).execution_options(synchronize_session=False))
    if result.rowcount != 1:
        db.rollback()
        raise HTTPException(409, "Publication lease is no longer owned by this worker")
    publication = db.query(Publication).populate_existing().filter(Publication.id == publication_id).first()
    audit(
        db,
        publication.channel.workspace_id,
        "publication",
        publication.id,
        "heartbeat",
        event_type="publication.heartbeat",
        metadata={"worker_id": worker_id},
    )
    event = PublicationEvent("heartbeat", publication.id, publication.status, publication.worker_id, publication.attempt_count)
    db.commit()
    publication_event(event.event, event.publication_id, status=event.status, worker_id=event.worker_id, attempt_count=event.attempt_count)
    return publication


def complete(db: Session, publication_id: int, worker_id: str, processing_token: str, external_id: str) -> Publication:
    now = datetime.utcnow()
    result = db.execute(update(Publication).where(
        Publication.id == publication_id, Publication.status == "processing",
        Publication.worker_id == worker_id, Publication.processing_token == processing_token,
        Publication.lease_heartbeat_at >= lease_cutoff(now),
    ).values(
        status="published", published_at=now, external_id=external_id,
        processing_started_at=None, lease_heartbeat_at=None, next_attempt_at=None,
        worker_id=None, processing_token=None,
    ).execution_options(synchronize_session=False))
    if result.rowcount != 1:
        db.rollback()
        raise HTTPException(409, "Publication lease is no longer owned by this worker")
    publication = db.query(Publication).populate_existing().filter(Publication.id == publication_id).first()
    operation = publication.provider_operation
    if operation:
        operation.status = "succeeded"
        operation.external_id = external_id
        operation.last_error = None
        operation.updated_at = now
    sync_content_status(db, publication.content)
    audit(
        db,
        publication.channel.workspace_id,
        "publication",
        publication.id,
        "published",
        event_type="publication.published",
        metadata={"external_id": external_id, "worker_id": worker_id, "attempt_count": publication.attempt_count},
    )
    event = PublicationEvent("completed", publication.id, publication.status, attempt_count=publication.attempt_count)
    db.commit()
    publication_event(event.event, event.publication_id, status=event.status, attempt_count=event.attempt_count)
    return publication


def fail(db: Session, publication_id: int, worker_id: str, processing_token: str, error_message: str, retry: bool) -> Publication:
    now = datetime.utcnow()
    publication = db.query(Publication).filter(Publication.id == publication_id).first()
    if not publication:
        raise HTTPException(404, "Publication not found")
    if publication.status != "processing" or publication.worker_id != worker_id or publication.processing_token != processing_token or not publication.lease_heartbeat_at or publication.lease_heartbeat_at < lease_cutoff(now):
        raise HTTPException(409, "Publication lease is no longer owned by this worker")
    target_status = "scheduled" if retry and publication.attempt_count < retry_max_attempts() else "failed"
    next_attempt_at = now + timedelta(seconds=retry_delay_seconds(publication.attempt_count)) if target_status == "scheduled" else None
    result = db.execute(update(Publication).where(
        Publication.id == publication_id, Publication.status == "processing",
        Publication.worker_id == worker_id, Publication.processing_token == processing_token,
        Publication.lease_heartbeat_at >= lease_cutoff(now),
    ).values(
        status=target_status, error_message=error_message, next_attempt_at=next_attempt_at,
        processing_started_at=None, processing_token=None, lease_heartbeat_at=None, worker_id=None,
    ).execution_options(synchronize_session=False))
    if result.rowcount != 1:
        db.rollback()
        raise HTTPException(409, "Publication lease is no longer owned by this worker")
    publication = db.query(Publication).populate_existing().filter(Publication.id == publication_id).first()
    operation = publication.provider_operation
    if operation:
        operation.status = "failed" if retry else "unknown"
        operation.last_error = error_message
        operation.updated_at = now
    sync_content_status(db, publication.content)
    audit(
        db,
        publication.channel.workspace_id,
        "publication",
        publication.id,
        "failed",
        event_type="publication.failed" if target_status == "failed" else "publication.retry_scheduled",
        metadata={"worker_id": worker_id, "attempt_count": publication.attempt_count, "retry": target_status == "scheduled", "error_message": error_message},
    )
    event_name = "retry_scheduled" if target_status == "scheduled" else ("provider_outcome_unknown" if not retry else "failed")
    event = PublicationEvent(event_name, publication.id, publication.status, attempt_count=publication.attempt_count, error=publication.error_message)
    db.commit()
    db.refresh(publication)
    publication_event(event.event, event.publication_id, status=event.status, attempt_count=event.attempt_count, error=event.error)
    return publication


def reconcile_unknown(
    db: Session,
    publication_id: int,
    outcome: str,
    external_id: str | None = None,
    error_message: str | None = None,
) -> Publication:
    """Resolve an unknown provider outcome without blindly replaying the side effect."""
    now = datetime.utcnow()
    publication = db.query(Publication).filter(Publication.id == publication_id).first()
    if not publication:
        raise HTTPException(404, "Publication not found")
    operation = publication.provider_operation
    if operation is None:
        raise HTTPException(500, "Publication provider operation is missing")
    if operation.status != "unknown" or publication.status != "failed":
        raise HTTPException(409, "Publication is not awaiting provider reconciliation")

    if outcome == "published":
        if not external_id:
            raise HTTPException(422, "external_id is required when outcome is published")
        publication.status = "published"
        publication.published_at = now
        publication.external_id = external_id
        publication.next_attempt_at = None
        publication.error_message = None
        operation.status = "succeeded"
        operation.external_id = external_id
        operation.last_error = None
        audit(
            db,
            publication.channel.workspace_id,
            "publication",
            publication.id,
            "reconciled_published",
            event_type="publication.reconciled_published",
            metadata={"external_id": external_id},
        )
        sync_content_status(db, publication.content)
        event_name = "reconciled_published"
    elif outcome == "retry":
        if publication.attempt_count >= retry_max_attempts():
            raise HTTPException(409, "Publication has reached the maximum retry attempts")
        publication.status = "scheduled"
        publication.next_attempt_at = now
        publication.error_message = error_message or "Provider outcome reconciled as retryable"
        operation.status = "pending"
        operation.last_error = publication.error_message
        audit(
            db,
            publication.channel.workspace_id,
            "publication",
            publication.id,
            "reconciled_retry",
            event_type="publication.reconciled_retry",
            metadata={"error_message": publication.error_message},
        )
        sync_content_status(db, publication.content)
        event_name = "reconciled_retry"
    else:
        raise HTTPException(422, "Unsupported reconciliation outcome")

    operation.updated_at = now
    db.commit()
    db.refresh(publication)
    publication_event(event_name, publication.id, status=publication.status, attempt_count=publication.attempt_count, error=publication.error_message)
    return publication
