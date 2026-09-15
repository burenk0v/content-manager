import os
import uuid
from datetime import datetime, timedelta
from typing import List, Optional

from fastapi import APIRouter, Depends, Header, HTTPException, status
from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy import and_, or_, update
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from src.app.db import get_db
from src.app.models import AuditLog, Channel, Content, ContentVersion, Publication, Workspace
from src.app.observability import publication_event
from src.app.publication_state import sync_content_status

router = APIRouter()

DEFAULT_LEASE_TIMEOUT_SECONDS = 900
MIN_LEASE_TIMEOUT_SECONDS = 60
MAX_LEASE_TIMEOUT_SECONDS = 86400
DEFAULT_MAX_ATTEMPTS = 5
DEFAULT_RETRY_DELAY_SECONDS = 60
DEFAULT_RETRY_MAX_DELAY_SECONDS = 3600


class WorkspaceCreate(BaseModel):
    name: str = Field(..., min_length=1, max_length=200)
    slug: str = Field(..., min_length=1, max_length=100)


class WorkspaceOut(WorkspaceCreate):
    id: int
    created_at: datetime
    model_config = ConfigDict(from_attributes=True)


class ChannelCreate(BaseModel):
    workspace_id: int
    platform: str = Field(..., min_length=1, max_length=50)
    external_id: str = Field(..., min_length=1, max_length=255)
    name: Optional[str] = None
    timezone: str = "UTC"


class ChannelOut(ChannelCreate):
    id: int
    is_active: bool
    created_at: datetime
    model_config = ConfigDict(from_attributes=True)


class ContentCreate(BaseModel):
    workspace_id: int
    title: Optional[str] = None
    body: str = Field(..., min_length=1)
    language: str = Field(..., min_length=2, max_length=10)
    source: str = Field("human", min_length=1, max_length=50)
    created_by: Optional[int] = None


class ContentOut(BaseModel):
    id: int
    workspace_id: int
    title: Optional[str]
    body: str
    language: str
    status: str
    created_by: Optional[int]
    created_at: datetime
    updated_at: datetime
    model_config = ConfigDict(from_attributes=True)


class ContentVersionOut(BaseModel):
    id: int
    content_id: int
    version: int
    body: str
    source: str
    created_by: Optional[int]
    created_at: datetime
    model_config = ConfigDict(from_attributes=True)


class PublicationCreate(BaseModel):
    content_id: int
    channel_id: int
    scheduled_at: Optional[datetime] = None
    idempotency_key: Optional[str] = None


class PublicationOut(BaseModel):
    id: int
    content_id: int
    channel_id: int
    status: str
    scheduled_at: Optional[datetime]
    published_at: Optional[datetime]
    processing_started_at: Optional[datetime]
    processing_token: Optional[str]
    lease_heartbeat_at: Optional[datetime]
    next_attempt_at: Optional[datetime]
    attempt_count: int
    worker_id: Optional[str]
    external_id: Optional[str]
    idempotency_key: str
    error_message: Optional[str]
    created_at: datetime
    model_config = ConfigDict(from_attributes=True)


class PublicationReadyOut(PublicationOut):
    content_body: str
    channel_platform: str
    channel_external_id: str


class PublicationClaim(BaseModel):
    worker_id: str = Field(..., min_length=1, max_length=200)


class PublicationLease(BaseModel):
    worker_id: str = Field(..., min_length=1, max_length=200)
    processing_token: str = Field(..., min_length=1, max_length=64)


class PublicationComplete(PublicationLease):
    external_id: str = Field(..., min_length=1, max_length=255)


class PublicationFail(PublicationLease):
    error_message: str = Field(..., min_length=1, max_length=4000)
    retry: bool = True


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


def require_service_token(x_service_token: Optional[str] = Header(None)) -> None:
    expected = os.environ.get("SERVICE_ACCOUNT_TOKEN")
    if not expected or x_service_token != expected:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid service token")


def audit(db: Session, workspace_id: int, entity_type: str, entity_id: int, action: str) -> None:
    db.add(AuditLog(workspace_id=workspace_id, entity_type=entity_type, entity_id=entity_id, action=action))


def transition_content(db: Session, content: Content, target: str) -> None:
    if content.status == target:
        return
    from src.app.content_lifecycle import transition_or_raise
    transition_or_raise(content.status, target)
    content.status = target
    content.updated_at = datetime.utcnow()
    audit(db, content.workspace_id, "content", content.id, "status_changed")


def publication_ready_out(publication: Publication) -> PublicationReadyOut:
    return PublicationReadyOut(
        **PublicationOut.model_validate(publication).model_dump(),
        content_body=publication.content.body,
        channel_platform=publication.channel.platform,
        channel_external_id=publication.channel.external_id,
    )


@router.post("/workspaces", response_model=WorkspaceOut, status_code=201, dependencies=[Depends(require_service_token)])
def create_workspace(payload: WorkspaceCreate, db: Session = Depends(get_db)):
    slug = payload.slug.strip().lower()
    if db.query(Workspace).filter(Workspace.slug == slug).first():
        raise HTTPException(409, "Workspace slug already exists")
    workspace = Workspace(name=payload.name.strip(), slug=slug)
    db.add(workspace)
    db.flush()
    audit(db, workspace.id, "workspace", workspace.id, "created")
    db.commit()
    db.refresh(workspace)
    return workspace


@router.get("/workspaces", response_model=List[WorkspaceOut], dependencies=[Depends(require_service_token)])
def list_workspaces(db: Session = Depends(get_db)):
    return db.query(Workspace).order_by(Workspace.created_at.desc()).all()


@router.post("/channels", response_model=ChannelOut, status_code=201, dependencies=[Depends(require_service_token)])
def create_channel(payload: ChannelCreate, db: Session = Depends(get_db)):
    if not db.query(Workspace).filter(Workspace.id == payload.workspace_id).first():
        raise HTTPException(404, "Workspace not found")
    channel = Channel(**payload.model_dump())
    db.add(channel)
    try:
        db.flush()
    except IntegrityError:
        db.rollback()
        raise HTTPException(409, "Channel already exists")
    audit(db, channel.workspace_id, "channel", channel.id, "created")
    db.commit()
    db.refresh(channel)
    return channel


@router.get("/channels", response_model=List[ChannelOut], dependencies=[Depends(require_service_token)])
def list_channels(workspace_id: Optional[int] = None, db: Session = Depends(get_db)):
    query = db.query(Channel)
    if workspace_id is not None:
        query = query.filter(Channel.workspace_id == workspace_id)
    return query.order_by(Channel.created_at.desc()).all()


@router.post("/contents", response_model=ContentOut, status_code=201, dependencies=[Depends(require_service_token)])
def create_content(payload: ContentCreate, db: Session = Depends(get_db)):
    if not db.query(Workspace).filter(Workspace.id == payload.workspace_id).first():
        raise HTTPException(404, "Workspace not found")
    content = Content(workspace_id=payload.workspace_id, title=payload.title, body=payload.body, language=payload.language.lower(), created_by=payload.created_by, status="draft")
    db.add(content)
    db.flush()
    db.add(ContentVersion(content_id=content.id, version=1, body=payload.body, source=payload.source, created_by=payload.created_by))
    audit(db, content.workspace_id, "content", content.id, "created")
    db.commit()
    db.refresh(content)
    return content


@router.get("/contents", response_model=List[ContentOut], dependencies=[Depends(require_service_token)])
def list_contents(workspace_id: Optional[int] = None, db: Session = Depends(get_db)):
    query = db.query(Content)
    if workspace_id is not None:
        query = query.filter(Content.workspace_id == workspace_id)
    return query.order_by(Content.created_at.asc(), Content.id.asc()).all()


@router.get("/contents/{content_id}/versions", response_model=List[ContentVersionOut], dependencies=[Depends(require_service_token)])
def list_content_versions(content_id: int, db: Session = Depends(get_db)):
    if not db.query(Content).filter(Content.id == content_id).first():
        raise HTTPException(404, "Content not found")
    return db.query(ContentVersion).filter(ContentVersion.content_id == content_id).order_by(ContentVersion.version.desc()).all()


@router.post("/publications", response_model=PublicationOut, status_code=201, dependencies=[Depends(require_service_token)])
def create_publication(payload: PublicationCreate, db: Session = Depends(get_db)):
    content = db.query(Content).filter(Content.id == payload.content_id).first()
    channel = db.query(Channel).filter(Channel.id == payload.channel_id).first()
    if not content:
        raise HTTPException(404, "Content not found")
    if not channel:
        raise HTTPException(404, "Channel not found")
    if content.workspace_id != channel.workspace_id:
        raise HTTPException(400, "Content and channel must belong to the same workspace")
    key = payload.idempotency_key or f"content:{content.id}:channel:{channel.id}:scheduled:{payload.scheduled_at or 'now'}"
    existing = db.query(Publication).filter(Publication.idempotency_key == key).first()
    if existing:
        return existing
    if content.status not in {"approved", "scheduled"}:
        raise HTTPException(409, "Content must be approved or scheduled before adding a publication")
    publication = Publication(content_id=content.id, channel_id=channel.id, scheduled_at=payload.scheduled_at, idempotency_key=key, status="scheduled")
    db.add(publication)
    try:
        db.flush()
    except IntegrityError:
        db.rollback()
        duplicate = db.query(Publication).filter(Publication.content_id == payload.content_id, Publication.channel_id == payload.channel_id).first()
        if duplicate:
            raise HTTPException(409, "Publication already exists for this content and channel")
        existing = db.query(Publication).filter(Publication.idempotency_key == key).first()
        if existing:
            return existing
        raise
    if content.status == "approved":
        transition_content(db, content, "scheduled")
    audit(db, content.workspace_id, "publication", publication.id, "scheduled")
    db.commit()
    db.refresh(publication)
    publication_event("scheduled", publication.id, status=publication.status, attempt_count=publication.attempt_count)
    return publication


@router.get("/publications/ready", response_model=List[PublicationReadyOut], dependencies=[Depends(require_service_token)])
def list_ready_publications(limit: int = 20, db: Session = Depends(get_db)):
    now = datetime.utcnow()
    query = db.query(Publication).join(Content).join(Channel).filter(Publication.status == "scheduled", or_(Publication.scheduled_at.is_(None), Publication.scheduled_at <= now), or_(Publication.next_attempt_at.is_(None), Publication.next_attempt_at <= now), Channel.is_active.is_(True)).order_by(Publication.id.asc()).limit(max(1, min(limit, 100)))
    return [publication_ready_out(item) for item in query.all()]


@router.get("/publications", response_model=List[PublicationOut], dependencies=[Depends(require_service_token)])
def list_publications(workspace_id: Optional[int] = None, db: Session = Depends(get_db)):
    query = db.query(Publication).join(Channel)
    if workspace_id is not None:
        query = query.filter(Channel.workspace_id == workspace_id)
    return query.order_by(Publication.scheduled_at.asc(), Publication.id.asc()).all()


@router.post("/publications/recover-stale", response_model=List[PublicationOut], dependencies=[Depends(require_service_token)])
def recover_stale_publications(db: Session = Depends(get_db)):
    now = datetime.utcnow()
    cutoff = lease_cutoff(now)
    stale_ids = [item.id for item in db.query(Publication.id).filter(Publication.status == "processing", or_(and_(Publication.lease_heartbeat_at.is_not(None), Publication.lease_heartbeat_at < cutoff), and_(Publication.lease_heartbeat_at.is_(None), Publication.processing_started_at.is_not(None), Publication.processing_started_at < cutoff))).all()]
    recovered = []
    for publication_id in stale_ids:
        result = db.execute(update(Publication).where(Publication.id == publication_id, Publication.status == "processing", or_(and_(Publication.lease_heartbeat_at.is_not(None), Publication.lease_heartbeat_at < cutoff), and_(Publication.lease_heartbeat_at.is_(None), Publication.processing_started_at.is_not(None), Publication.processing_started_at < cutoff))).values(status="scheduled", next_attempt_at=now, processing_started_at=None, processing_token=None, lease_heartbeat_at=None, worker_id=None, error_message="Recovered stale processing claim").execution_options(synchronize_session=False))
        if result.rowcount != 1:
            continue
        publication = db.query(Publication).populate_existing().filter(Publication.id == publication_id).first()
        sync_content_status(db, publication.content)
        recovered.append(publication)
    if recovered:
        db.commit()
        for publication in recovered:
            db.refresh(publication)
            publication_event("recovered", publication.id, status=publication.status, attempt_count=publication.attempt_count)
    return recovered


@router.post("/publications/{publication_id}/claim", response_model=PublicationOut, dependencies=[Depends(require_service_token)])
def claim_publication(publication_id: int, payload: PublicationClaim, db: Session = Depends(get_db)):
    now = datetime.utcnow()
    processing_token = uuid.uuid4().hex
    eligible = and_(or_(Publication.scheduled_at.is_(None), Publication.scheduled_at <= now), or_(Publication.next_attempt_at.is_(None), Publication.next_attempt_at <= now))
    result = db.execute(update(Publication).where(Publication.id == publication_id, Publication.status == "scheduled", eligible).values(status="processing", processing_started_at=now, processing_token=processing_token, lease_heartbeat_at=now, worker_id=payload.worker_id, attempt_count=Publication.attempt_count + 1, error_message=None).execution_options(synchronize_session=False))
    if result.rowcount != 1:
        db.rollback()
        publication = db.query(Publication).filter(Publication.id == publication_id).first()
        if not publication:
            raise HTTPException(404, "Publication not found")
        raise HTTPException(409, "Publication is not claimable")
    publication = db.query(Publication).populate_existing().filter(Publication.id == publication_id).first()
    if publication.content.status != "publishing":
        transition_content(db, publication.content, "publishing")
    response = PublicationOut.model_validate(publication)
    event_data = (publication.id, publication.status, publication.worker_id, publication.attempt_count)
    db.commit()
    publication_event("claimed", event_data[0], status=event_data[1], worker_id=event_data[2], attempt_count=event_data[3])
    return response


@router.post("/publications/{publication_id}/heartbeat", response_model=PublicationOut, dependencies=[Depends(require_service_token)])
def heartbeat_publication(publication_id: int, payload: PublicationLease, db: Session = Depends(get_db)):
    now = datetime.utcnow()
    result = db.execute(update(Publication).where(Publication.id == publication_id, Publication.status == "processing", Publication.worker_id == payload.worker_id, Publication.processing_token == payload.processing_token, Publication.lease_heartbeat_at >= lease_cutoff(now)).values(lease_heartbeat_at=now).execution_options(synchronize_session=False))
    if result.rowcount != 1:
        db.rollback()
        raise HTTPException(409, "Publication lease is no longer owned by this worker")
    publication = db.query(Publication).populate_existing().filter(Publication.id == publication_id).first()
    event_data = (publication.id, publication.status, publication.worker_id, publication.attempt_count)
    db.commit()
    publication_event("heartbeat", event_data[0], status=event_data[1], worker_id=event_data[2], attempt_count=event_data[3])
    return publication


@router.post("/publications/{publication_id}/complete", response_model=PublicationOut, dependencies=[Depends(require_service_token)])
def complete_publication(publication_id: int, payload: PublicationComplete, db: Session = Depends(get_db)):
    now = datetime.utcnow()
    result = db.execute(update(Publication).where(Publication.id == publication_id, Publication.status == "processing", Publication.worker_id == payload.worker_id, Publication.processing_token == payload.processing_token, Publication.lease_heartbeat_at >= lease_cutoff(now)).values(status="published", published_at=now, external_id=payload.external_id, processing_started_at=None, lease_heartbeat_at=None, next_attempt_at=None, worker_id=None, processing_token=None).execution_options(synchronize_session=False))
    if result.rowcount != 1:
        db.rollback()
        raise HTTPException(409, "Publication lease is no longer owned by this worker")
    publication = db.query(Publication).populate_existing().filter(Publication.id == publication_id).first()
    sync_content_status(db, publication.content)
    audit(db, publication.channel.workspace_id, "publication", publication.id, "published")
    event_data = (publication.id, publication.status, publication.attempt_count)
    db.commit()
    publication_event("completed", event_data[0], status=event_data[1], attempt_count=event_data[2])
    return publication


@router.post("/publications/{publication_id}/fail", response_model=PublicationOut, dependencies=[Depends(require_service_token)])
def fail_publication(publication_id: int, payload: PublicationFail, db: Session = Depends(get_db)):
    now = datetime.utcnow()
    publication = db.query(Publication).filter(Publication.id == publication_id).first()
    if not publication:
        raise HTTPException(404, "Publication not found")
    if publication.status != "processing" or publication.worker_id != payload.worker_id or publication.processing_token != payload.processing_token or not publication.lease_heartbeat_at or publication.lease_heartbeat_at < lease_cutoff(now):
        raise HTTPException(409, "Publication lease is no longer owned by this worker")
    publication.error_message = payload.error_message
    if payload.retry and publication.attempt_count < retry_max_attempts():
        publication.status = "scheduled"
        publication.next_attempt_at = now + timedelta(seconds=retry_delay_seconds(publication.attempt_count))
    else:
        publication.status = "failed"
        publication.next_attempt_at = None
    publication.processing_started_at = None
    publication.processing_token = None
    publication.lease_heartbeat_at = None
    publication.worker_id = None
    sync_content_status(db, publication.content)
    audit(db, publication.channel.workspace_id, "publication", publication.id, "failed")
    event_name = "retry_scheduled" if publication.status == "scheduled" else "failed"
    event_data = (publication.id, publication.status, publication.attempt_count, publication.error_message)
    db.commit()
    db.refresh(publication)
    publication_event(event_name, event_data[0], status=event_data[1], attempt_count=event_data[2], error=event_data[3])
    return publication
