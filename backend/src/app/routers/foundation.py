from datetime import datetime, timedelta
from typing import List, Optional
import hmac
import os
import uuid

from fastapi import APIRouter, Depends, Header, HTTPException, status
from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from src.app.audit import audit
from src.app.db import get_db
from src.app.domain.content_state_machine import transition
from src.app.models import Channel, Content, ContentProfile, ContentVersion, Publication, PublicationOperation, Workspace
from src.app.observability import publication_event
from src.app.services import publication_service

router = APIRouter()


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
    profile_id: Optional[int] = None
    title: Optional[str] = None
    body: str = Field(..., min_length=1)
    language: str = Field(..., min_length=2, max_length=10)
    source: str = Field("human", min_length=1, max_length=50)
    created_by: Optional[int] = None


class ContentUpdate(BaseModel):
    body: str = Field(..., min_length=1)
    source: str = Field("human", min_length=1, max_length=50)
    created_by: Optional[int] = None


class ContentOut(BaseModel):
    id: int
    workspace_id: int
    profile_id: Optional[int]
    title: Optional[str]
    body: str
    language: str
    status: str
    created_by: Optional[int]
    approval_notification_claimed_at: Optional[datetime] = None
    approval_notification_sent_at: Optional[datetime] = None
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
    content_version_id: int
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
    provider_operation_key: Optional[str] = None
    provider_operation_status: Optional[str] = None
    provider_operation_attempt_count: int = 0
    error_message: Optional[str]
    created_at: datetime
    model_config = ConfigDict(from_attributes=True)


class PublicationReadyOut(PublicationOut):
    content_body: str
    channel_platform: str
    channel_external_id: str


class PublicationUnknownOut(PublicationOut):
    channel_platform: str
    channel_external_id: str


class PublicationClaim(BaseModel):
    worker_id: str = Field(..., min_length=1, max_length=200)


class PublicationLease(BaseModel):
    worker_id: str = Field(..., min_length=1, max_length=200)
    processing_token: str = Field(..., min_length=1, max_length=64)


class PublicationComplete(PublicationLease):
    external_id: str = Field(..., min_length=1, max_length=255)


class PublicationFail(BaseModel):
    worker_id: str = Field(..., min_length=1, max_length=200)
    processing_token: str = Field(..., min_length=1, max_length=64)
    error_message: str = Field(..., min_length=1, max_length=4000)
    retry: bool = True


class PublicationReconciliation(BaseModel):
    outcome: str = Field(..., pattern="^(published|retry)$")
    external_id: Optional[str] = Field(None, min_length=1, max_length=255)
    error_message: Optional[str] = Field(None, min_length=1, max_length=4000)


def require_service_token(x_service_token: Optional[str] = Header(None)) -> None:
    expected = os.environ.get("SERVICE_ACCOUNT_TOKEN")
    if not expected or not x_service_token or not hmac.compare_digest(x_service_token, expected):
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid service token")


def publication_out(publication: Publication) -> PublicationOut:
    operation = publication.provider_operation
    data = PublicationOut.model_validate(publication).model_dump()
    data.update(provider_operation_key=operation.operation_key if operation else None, provider_operation_status=operation.status if operation else None, provider_operation_attempt_count=operation.attempt_count if operation else 0)
    return PublicationOut(**data)


def publication_ready_out(publication: Publication) -> PublicationReadyOut:
    data = publication_out(publication).model_dump()
    data.update(content_body=publication.content_version.body, channel_platform=publication.channel.platform, channel_external_id=publication.channel.external_id)
    return PublicationReadyOut(**data)


def publication_unknown_out(publication: Publication) -> PublicationUnknownOut:
    data = publication_out(publication).model_dump()
    data.update(channel_platform=publication.channel.platform, channel_external_id=publication.channel.external_id)
    return PublicationUnknownOut(**data)


@router.post("/workspaces", response_model=WorkspaceOut, status_code=201, dependencies=[Depends(require_service_token)])
def create_workspace(payload: WorkspaceCreate, db: Session = Depends(get_db)):
    slug = payload.slug.strip().lower()
    if db.query(Workspace).filter(Workspace.slug == slug).first():
        raise HTTPException(409, "Workspace slug already exists")
    workspace = Workspace(name=payload.name.strip(), slug=slug)
    db.add(workspace)
    db.flush()
    audit(db, workspace.id, "workspace", workspace.id, "created", event_type="workspace.created")
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
    audit(db, channel.workspace_id, "channel", channel.id, "created", event_type="channel.created")
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
    if payload.profile_id is not None:
        profile = db.query(ContentProfile).filter(ContentProfile.id == payload.profile_id).first()
        if not profile:
            raise HTTPException(404, "Content profile not found")
        if profile.workspace_id != payload.workspace_id:
            raise HTTPException(400, "Content profile must belong to the workspace")
    content = Content(workspace_id=payload.workspace_id, profile_id=payload.profile_id, title=payload.title, language=payload.language.lower(), created_by=payload.created_by, status="draft")
    db.add(content)
    db.flush()
    db.add(ContentVersion(content_id=content.id, version=1, body=payload.body, source=payload.source, created_by=payload.created_by))
    audit(db, content.workspace_id, "content", content.id, "created", actor_user_id=payload.created_by, event_type="content.created", metadata={"language": content.language, "source": payload.source})
    db.commit()
    db.refresh(content)
    return content


@router.post("/contents/{content_id}/versions", response_model=ContentVersionOut, status_code=201, dependencies=[Depends(require_service_token)])
def create_content_version(content_id: int, payload: ContentUpdate, db: Session = Depends(get_db)):
    content = db.query(Content).filter(Content.id == content_id).first()
    if not content:
        raise HTTPException(404, "Content not found")
    if content.status not in {"draft", "review", "approved", "scheduled"}:
        raise HTTPException(409, "Content version cannot be changed in its current state")

    previous_status = content.status
    latest = content.current_version
    version = ContentVersion(content_id=content.id, version=latest.version + 1, body=payload.body, source=payload.source, created_by=payload.created_by)
    db.add(version)

    metadata = {"version": version.version, "source": payload.source}
    if previous_status in {"approved", "scheduled"}:
        transition(previous_status, "draft")
        content.status = "draft"
        metadata["approval_invalidated"] = True
        metadata["from_status"] = previous_status
        metadata["to_status"] = "draft"
        audit(db, content.workspace_id, "content", content.id, "status_changed", actor_user_id=payload.created_by, event_type="content.approval_invalidated", metadata=metadata)

    content.updated_at = datetime.utcnow()
    audit(db, content.workspace_id, "content_version", version.id, "created", actor_user_id=payload.created_by, event_type="content_version.created", metadata=metadata)
    db.commit()
    db.refresh(version)
    return version


@router.get("/contents", response_model=List[ContentOut], dependencies=[Depends(require_service_token)])
def list_contents(workspace_id: Optional[int] = None, db: Session = Depends(get_db)):
    query = db.query(Content)
    if workspace_id is not None:
        query = query.filter(Content.workspace_id == workspace_id)
    return query.order_by(Content.created_at.asc(), Content.id.asc()).all()


@router.post("/contents/{content_id}/notification-claim", response_model=ContentOut, dependencies=[Depends(require_service_token)])
def claim_content_notification(content_id: int, db: Session = Depends(get_db)):
    now = datetime.utcnow()
    content = db.query(Content).filter(Content.id == content_id).with_for_update().first()
    if not content or content.status != "review" or content.approval_notification_sent_at is not None:
        raise HTTPException(409, "Content notification is not available")
    if content.approval_notification_claimed_at and content.approval_notification_claimed_at > now - timedelta(minutes=5):
        raise HTTPException(409, "Content notification is already claimed")
    content.approval_notification_claimed_at = now
    db.commit()
    db.refresh(content)
    return content


@router.post("/contents/{content_id}/notification-complete", response_model=ContentOut, dependencies=[Depends(require_service_token)])
def complete_content_notification(content_id: int, db: Session = Depends(get_db)):
    content = db.query(Content).filter(Content.id == content_id).first()
    if not content or content.status != "review":
        raise HTTPException(409, "Content notification is not available")
    content.approval_notification_sent_at = datetime.utcnow()
    content.approval_notification_claimed_at = None
    db.commit()
    db.refresh(content)
    return content


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
        return publication_out(existing)
    if content.status not in {"approved", "scheduled"}:
        raise HTTPException(409, "Content must be approved or scheduled before adding a publication")
    publication = Publication(content_id=content.id, content_version_id=content.current_version.id, channel_id=channel.id, scheduled_at=payload.scheduled_at, idempotency_key=key, status="scheduled")
    db.add(publication)
    try:
        db.flush()
        db.add(PublicationOperation(publication_id=publication.id, provider=channel.platform.strip().lower(), operation_key=f"publication:{uuid.uuid4().hex}", status="pending"))
        db.flush()
    except IntegrityError:
        db.rollback()
        duplicate = db.query(Publication).filter(Publication.content_id == payload.content_id, Publication.channel_id == payload.channel_id).first()
        if duplicate:
            raise HTTPException(409, "Publication already exists for this content and channel")
        existing = db.query(Publication).filter(Publication.idempotency_key == key).first()
        if existing:
            return publication_out(existing)
        raise
    if content.status == "approved":
        transition(content.status, "scheduled")
        content.status = "scheduled"
        content.updated_at = datetime.utcnow()
        audit(db, content.workspace_id, "content", content.id, "status_changed", event_type="content.status_changed", metadata={"from": "approved", "to": "scheduled"})
    audit(db, content.workspace_id, "publication", publication.id, "scheduled", event_type="publication.scheduled", metadata={"channel_id": channel.id, "content_version_id": publication.content_version_id})
    db.commit()
    db.refresh(publication)
    publication_event("scheduled", publication.id, status=publication.status, attempt_count=publication.attempt_count)
    return publication_out(publication)


@router.post("/contents/{content_id}/approve-and-schedule", response_model=PublicationOut, status_code=201, dependencies=[Depends(require_service_token)])
def approve_and_schedule_content(content_id: int, payload: PublicationCreate, db: Session = Depends(get_db)):
    """Atomically approve content and create its publication."""
    if payload.content_id != content_id:
        raise HTTPException(400, "content_id does not match the path")
    content = db.query(Content).filter(Content.id == content_id).with_for_update().first()
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
        return publication_out(existing)
    existing_for_content = db.query(Publication).filter(
        Publication.content_id == content.id,
        Publication.channel_id == channel.id,
    ).first()
    if existing_for_content:
        return publication_out(existing_for_content)

    if content.status == "review":
        transition(content.status, "approved")
        content.status = "approved"
    if content.status != "approved":
        raise HTTPException(409, "Content must be in review or approved state")
    publication = Publication(
        content_id=content.id,
        content_version_id=content.current_version.id,
        channel_id=channel.id,
        scheduled_at=payload.scheduled_at,
        idempotency_key=key,
        status="scheduled",
    )
    db.add(publication)
    try:
        db.flush()
        db.add(PublicationOperation(
            publication_id=publication.id,
            provider=channel.platform.strip().lower(),
            operation_key=f"publication:{uuid.uuid4().hex}",
            status="pending",
        ))
        db.flush()
    except IntegrityError:
        db.rollback()
        existing = db.query(Publication).filter(
            Publication.content_id == content.id,
            Publication.channel_id == channel.id,
        ).first()
        if existing:
            return publication_out(existing)
        raise
    transition("approved", "scheduled")
    content.status = "scheduled"
    content.updated_at = datetime.utcnow()
    audit(
        db,
        content.workspace_id,
        "content",
        content.id,
        "status_changed",
        event_type="content.status_changed",
        metadata={"from": "review", "to": "scheduled", "approval": True},
    )
    audit(
        db,
        content.workspace_id,
        "publication",
        publication.id,
        "scheduled",
        event_type="publication.scheduled",
        metadata={"channel_id": channel.id, "content_version_id": publication.content_version_id, "atomic_approval": True},
    )
    db.commit()
    db.refresh(publication)
    publication_event("scheduled", publication.id, status=publication.status, attempt_count=publication.attempt_count)
    return publication_out(publication)


@router.get("/publications/ready", response_model=List[PublicationReadyOut], dependencies=[Depends(require_service_token)])
def list_ready_publications(limit: int = 20, db: Session = Depends(get_db)):
    from sqlalchemy import or_
    now = datetime.utcnow()
    query = db.query(Publication).join(Content).join(Channel).filter(Publication.status == "scheduled", or_(Publication.scheduled_at.is_(None), Publication.scheduled_at <= now), or_(Publication.next_attempt_at.is_(None), Publication.next_attempt_at <= now), Channel.is_active.is_(True)).order_by(Publication.id.asc()).limit(max(1, min(limit, 100)))
    return [publication_ready_out(item) for item in query.all()]


@router.get("/publications/unknown", response_model=List[PublicationUnknownOut], dependencies=[Depends(require_service_token)])
def list_unknown_publications(limit: int = 20, db: Session = Depends(get_db)):
    query = db.query(Publication).join(PublicationOperation).join(Channel).filter(Publication.status == "failed", PublicationOperation.status == "unknown", Channel.is_active.is_(True)).order_by(Publication.id.asc()).limit(max(1, min(limit, 100)))
    return [publication_unknown_out(item) for item in query.all()]


@router.get("/publications", response_model=List[PublicationOut], dependencies=[Depends(require_service_token)])
def list_publications(workspace_id: Optional[int] = None, db: Session = Depends(get_db)):
    query = db.query(Publication).join(Channel)
    if workspace_id is not None:
        query = query.filter(Channel.workspace_id == workspace_id)
    return [publication_out(item) for item in query.order_by(Publication.scheduled_at.asc(), Publication.id.asc()).all()]


@router.post("/publications/recover-stale", response_model=List[PublicationOut], dependencies=[Depends(require_service_token)])
def recover_stale_publications(db: Session = Depends(get_db)):
    return [publication_out(item) for item in publication_service.recover_stale(db)]


@router.post("/publications/{publication_id}/claim", response_model=PublicationOut, dependencies=[Depends(require_service_token)])
def claim_publication(publication_id: int, payload: PublicationClaim, db: Session = Depends(get_db)):
    return publication_out(publication_service.claim(db, publication_id, payload.worker_id))


@router.post("/publications/{publication_id}/heartbeat", response_model=PublicationOut, dependencies=[Depends(require_service_token)])
def heartbeat_publication(publication_id: int, payload: PublicationLease, db: Session = Depends(get_db)):
    return publication_out(publication_service.heartbeat(db, publication_id, payload.worker_id, payload.processing_token))


@router.post("/publications/{publication_id}/complete", response_model=PublicationOut, dependencies=[Depends(require_service_token)])
def complete_publication(publication_id: int, payload: PublicationComplete, db: Session = Depends(get_db)):
    return publication_out(publication_service.complete(db, publication_id, payload.worker_id, payload.processing_token, payload.external_id))


@router.post("/publications/{publication_id}/fail", response_model=PublicationOut, dependencies=[Depends(require_service_token)])
def fail_publication(publication_id: int, payload: PublicationFail, db: Session = Depends(get_db)):
    return publication_out(publication_service.fail(db, publication_id, payload.worker_id, payload.processing_token, payload.error_message, payload.retry))


@router.post("/publications/{publication_id}/reconcile", response_model=PublicationOut, dependencies=[Depends(require_service_token)])
def reconcile_publication(publication_id: int, payload: PublicationReconciliation, db: Session = Depends(get_db)):
    return publication_out(publication_service.reconcile_unknown(db, publication_id, payload.outcome, payload.external_id, payload.error_message))
