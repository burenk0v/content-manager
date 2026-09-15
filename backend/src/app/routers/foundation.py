import os
from datetime import datetime, timedelta
from typing import List, Optional

from fastapi import APIRouter, Depends, Header, HTTPException, status
from pydantic import BaseModel, Field
from sqlalchemy import and_, or_, update
from sqlalchemy.orm import Session

from src.app.db import get_db
from src.app.models import AuditLog, Channel, Content, ContentVersion, PostDraft, Publication, PublicationSchedule, Workspace

router = APIRouter()


class WorkspaceCreate(BaseModel):
    name: str = Field(..., min_length=1, max_length=200)
    slug: str = Field(..., min_length=1, max_length=100)

class WorkspaceOut(WorkspaceCreate):
    id: int
    created_at: datetime
    class Config:
        orm_mode = True

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
    class Config:
        orm_mode = True

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
    class Config:
        orm_mode = True

class ContentVersionOut(BaseModel):
    id: int
    content_id: int
    version: int
    body: str
    source: str
    created_by: Optional[int]
    created_at: datetime
    class Config:
        orm_mode = True

class PublicationCreate(BaseModel):
    content_id: int
    channel_id: int
    scheduled_at: Optional[datetime] = None
    idempotency_key: Optional[str] = None

class PublicationOut(BaseModel):
    id: int
    content_id: int
    channel_id: int
    source_draft_id: Optional[int]
    status: str
    scheduled_at: Optional[datetime]
    published_at: Optional[datetime]
    processing_started_at: Optional[datetime]
    next_attempt_at: Optional[datetime]
    attempt_count: int
    worker_id: Optional[str]
    external_id: Optional[str]
    idempotency_key: str
    error_message: Optional[str]
    created_at: datetime
    class Config:
        orm_mode = True

class PublicationReadyOut(PublicationOut):
    content_body: str
    channel_platform: str
    channel_external_id: str

class PublicationClaim(BaseModel):
    worker_id: str = Field(..., min_length=1, max_length=200)

class PublicationComplete(BaseModel):
    worker_id: str = Field(..., min_length=1, max_length=200)
    external_id: str = Field(..., min_length=1, max_length=255)

class PublicationFail(BaseModel):
    worker_id: str = Field(..., min_length=1, max_length=200)
    error_message: str = Field(..., min_length=1, max_length=4000)
    retry: bool = True
    max_attempts: int = Field(5, ge=1, le=20)
    retry_delay_seconds: int = Field(60, ge=1, le=86400)


def require_service_token(x_service_token: Optional[str] = Header(None)) -> None:
    expected = os.environ.get("SERVICE_ACCOUNT_TOKEN")
    if not expected or x_service_token != expected:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid service token")


def audit(db: Session, workspace_id: int, entity_type: str, entity_id: int, action: str) -> None:
    db.add(AuditLog(workspace_id=workspace_id, entity_type=entity_type, entity_id=entity_id, action=action))


def publication_ready_out(publication: Publication) -> PublicationReadyOut:
    return PublicationReadyOut(
        id=publication.id,
        content_id=publication.content_id,
        channel_id=publication.channel_id,
        source_draft_id=publication.source_draft_id,
        status=publication.status,
        scheduled_at=publication.scheduled_at,
        published_at=publication.published_at,
        processing_started_at=publication.processing_started_at,
        next_attempt_at=publication.next_attempt_at,
        attempt_count=publication.attempt_count,
        worker_id=publication.worker_id,
        external_id=publication.external_id,
        idempotency_key=publication.idempotency_key,
        error_message=publication.error_message,
        created_at=publication.created_at,
        content_body=publication.content.body,
        channel_platform=publication.channel.platform,
        channel_external_id=publication.channel.external_id,
    )


def transition_content(db: Session, content: Content, target: str) -> None:
    from src.app.content_lifecycle import transition_or_raise
    if content.status == target:
        return
    transition_or_raise(content.status, target)
    previous = content.status
    content.status = target
    content.updated_at = datetime.utcnow()
    audit(db, content.workspace_id, "content", content.id, "status_changed")


@router.post("/workspaces", response_model=WorkspaceOut, status_code=201, dependencies=[Depends(require_service_token)])
def create_workspace(payload: WorkspaceCreate, db: Session = Depends(get_db)):
    slug = payload.slug.strip().lower()
    if db.query(Workspace).filter(Workspace.slug == slug).first():
        raise HTTPException(409, "Workspace slug already exists")
    workspace = Workspace(name=payload.name.strip(), slug=slug)
    db.add(workspace); db.flush()
    audit(db, workspace.id, "workspace", workspace.id, "created")
    db.commit(); db.refresh(workspace)
    return workspace

@router.get("/workspaces", response_model=List[WorkspaceOut], dependencies=[Depends(require_service_token)])
def list_workspaces(db: Session = Depends(get_db)):
    return db.query(Workspace).order_by(Workspace.created_at.desc()).all()

@router.post("/channels", response_model=ChannelOut, status_code=201, dependencies=[Depends(require_service_token)])
def create_channel(payload: ChannelCreate, db: Session = Depends(get_db)):
    if not db.query(Workspace).filter(Workspace.id == payload.workspace_id).first():
        raise HTTPException(404, "Workspace not found")
    channel = Channel(**payload.dict())
    db.add(channel); db.flush()
    audit(db, channel.workspace_id, "channel", channel.id, "created")
    db.commit(); db.refresh(channel)
    return channel

@router.get("/channels", response_model=List[ChannelOut], dependencies=[Depends(require_service_token)])
def list_channels(workspace_id: Optional[int] = None, db: Session = Depends(get_db)):
    query = db.query(Channel)
    if workspace_id is not None: query = query.filter(Channel.workspace_id == workspace_id)
    return query.order_by(Channel.created_at.desc()).all()

@router.post("/contents", response_model=ContentOut, status_code=201, dependencies=[Depends(require_service_token)])
def create_content(payload: ContentCreate, db: Session = Depends(get_db)):
    if not db.query(Workspace).filter(Workspace.id == payload.workspace_id).first():
        raise HTTPException(404, "Workspace not found")
    content = Content(workspace_id=payload.workspace_id, title=payload.title, body=payload.body, language=payload.language.lower(), created_by=payload.created_by, status="draft")
    db.add(content); db.flush()
    db.add(ContentVersion(content_id=content.id, version=1, body=payload.body, source=payload.source, created_by=payload.created_by))
    audit(db, content.workspace_id, "content", content.id, "created")
    db.commit(); db.refresh(content)
    return content

@router.get("/contents", response_model=List[ContentOut], dependencies=[Depends(require_service_token)])
def list_contents(workspace_id: Optional[int] = None, db: Session = Depends(get_db)):
    query = db.query(Content)
    if workspace_id is not None: query = query.filter(Content.workspace_id == workspace_id)
    return query.order_by(Content.updated_at.desc()).all()

@router.get("/contents/{content_id}/versions", response_model=List[ContentVersionOut], dependencies=[Depends(require_service_token)])
def list_content_versions(content_id: int, db: Session = Depends(get_db)):
    if not db.query(Content).filter(Content.id == content_id).first():
        raise HTTPException(404, "Content not found")
    return db.query(ContentVersion).filter(ContentVersion.content_id == content_id).order_by(ContentVersion.version.desc()).all()

@router.post("/publications/from-draft/{draft_id}", response_model=PublicationOut, status_code=201, dependencies=[Depends(require_service_token)])
def create_publication_from_draft(draft_id: int, db: Session = Depends(get_db)):
    draft = db.query(PostDraft).filter(PostDraft.id == draft_id).first()
    if not draft:
        raise HTTPException(404, "Draft not found")
    if draft.status not in {"pending", "scheduled"}:
        existing = db.query(Publication).filter(Publication.source_draft_id == draft_id).first()
        if existing:
            return existing
        raise HTTPException(409, "Draft is not publishable")
    schedule = db.query(PublicationSchedule).filter(PublicationSchedule.id == draft.schedule_id).first()
    if not schedule:
        raise HTTPException(404, "Schedule not found")
    key = f"draft:{draft.id}:publication"
    existing = db.query(Publication).filter(Publication.idempotency_key == key).first()
    if existing:
        return existing
    workspace = db.query(Workspace).filter(Workspace.slug == "telegram-default").first()
    if not workspace:
        workspace = Workspace(name="Telegram", slug="telegram-default")
        db.add(workspace); db.flush(); audit(db, workspace.id, "workspace", workspace.id, "created")
    channel = db.query(Channel).filter(Channel.platform == "telegram", Channel.external_id == schedule.chat_id).first()
    if not channel:
        channel = Channel(workspace_id=workspace.id, platform="telegram", external_id=schedule.chat_id, name=schedule.chat_name, timezone=schedule.timezone or "UTC")
        db.add(channel); db.flush(); audit(db, workspace.id, "channel", channel.id, "created")
    content = Content(workspace_id=workspace.id, title=draft.topic_name, body=draft.generated_text, language=draft.language, status="scheduled")
    db.add(content); db.flush()
    db.add(ContentVersion(content_id=content.id, version=1, body=draft.generated_text, source="ai", created_by=None))
    publication = Publication(content_id=content.id, channel_id=channel.id, source_draft_id=draft.id, status="scheduled", idempotency_key=key)
    db.add(publication); db.flush()
    audit(db, workspace.id, "content", content.id, "scheduled")
    audit(db, workspace.id, "publication", publication.id, "scheduled")
    db.commit(); db.refresh(publication)
    return publication

@router.post("/publications", response_model=PublicationOut, status_code=201, dependencies=[Depends(require_service_token)])
def create_publication(payload: PublicationCreate, db: Session = Depends(get_db)):
    content = db.query(Content).filter(Content.id == payload.content_id).first()
    channel = db.query(Channel).filter(Channel.id == payload.channel_id).first()
    if not content: raise HTTPException(404, "Content not found")
    if not channel: raise HTTPException(404, "Channel not found")
    if content.workspace_id != channel.workspace_id: raise HTTPException(400, "Content and channel must belong to the same workspace")
    key = payload.idempotency_key or f"content:{content.id}:channel:{channel.id}:scheduled:{payload.scheduled_at or 'now'}"
    existing = db.query(Publication).filter(Publication.idempotency_key == key).first()
    if existing: return existing
    if content.status != "approved":
        raise HTTPException(409, "Content must be approved before scheduling")
    publication = Publication(content_id=content.id, channel_id=channel.id, scheduled_at=payload.scheduled_at, idempotency_key=key, status="scheduled")
    db.add(publication); db.flush()
    transition_content(db, content, "scheduled")
    audit(db, content.workspace_id, "publication", publication.id, "scheduled")
    db.commit(); db.refresh(publication)
    return publication

@router.get("/publications/ready", response_model=List[PublicationReadyOut], dependencies=[Depends(require_service_token)])
def list_ready_publications(limit: int = 20, db: Session = Depends(get_db)):
    now = datetime.utcnow()
    query = db.query(Publication).join(Content).join(Channel).filter(Publication.status == "scheduled", or_(Publication.scheduled_at.is_(None), Publication.scheduled_at <= now), or_(Publication.next_attempt_at.is_(None), Publication.next_attempt_at <= now), Channel.is_active.is_(True)).order_by(Publication.id.asc()).limit(max(1, min(limit, 100)))
    return [publication_ready_out(publication) for publication in query.all()]

@router.get("/publications", response_model=List[PublicationOut], dependencies=[Depends(require_service_token)])
def list_publications(workspace_id: Optional[int] = None, db: Session = Depends(get_db)):
    query = db.query(Publication).join(Channel)
    if workspace_id is not None: query = query.filter(Channel.workspace_id == workspace_id)
    return query.order_by(Publication.scheduled_at.asc(), Publication.id.asc()).all()

@router.post("/publications/recover-stale", response_model=List[PublicationOut], dependencies=[Depends(require_service_token)])
def recover_stale_publications(stale_after_seconds: int = 900, db: Session = Depends(get_db)):
    cutoff = datetime.utcnow() - timedelta(seconds=max(60, min(stale_after_seconds, 86400)))
    stale = db.query(Publication).filter(Publication.status == "processing", Publication.processing_started_at.is_not(None), Publication.processing_started_at < cutoff).all()
    for publication in stale:
        publication.status = "scheduled"; publication.next_attempt_at = datetime.utcnow(); publication.processing_started_at = None; publication.worker_id = None; publication.error_message = "Recovered stale processing claim"
        if publication.content.status == "publishing":
            transition_content(db, publication.content, "scheduled")
    if stale:
        db.commit()
        for publication in stale: db.refresh(publication)
    return stale

@router.post("/publications/{publication_id}/claim", response_model=PublicationOut, dependencies=[Depends(require_service_token)])
def claim_publication(publication_id: int, payload: PublicationClaim, db: Session = Depends(get_db)):
    now = datetime.utcnow()
    eligible = and_(or_(Publication.scheduled_at.is_(None), Publication.scheduled_at <= now), or_(Publication.next_attempt_at.is_(None), Publication.next_attempt_at <= now))
    result = db.execute(update(Publication).where(Publication.id == publication_id, Publication.status == "scheduled", eligible).values(status="processing", processing_started_at=now, worker_id=payload.worker_id, attempt_count=Publication.attempt_count + 1, error_message=None))
    if result.rowcount != 1:
        db.rollback(); publication = db.query(Publication).filter(Publication.id == publication_id).first()
        if not publication: raise HTTPException(404, "Publication not found")
        raise HTTPException(409, "Publication is not claimable")
    publication = db.query(Publication).filter(Publication.id == publication_id).first()
    if publication.content.status == "scheduled":
        transition_content(db, publication.content, "publishing")
    db.commit()
    return db.query(Publication).filter(Publication.id == publication_id).first()

@router.post("/publications/{publication_id}/complete", response_model=PublicationOut, dependencies=[Depends(require_service_token)])
def complete_publication(publication_id: int, payload: PublicationComplete, db: Session = Depends(get_db)):
    now = datetime.utcnow()
    result = db.execute(update(Publication).where(Publication.id == publication_id, Publication.status == "processing", Publication.worker_id == payload.worker_id).values(status="published", published_at=now, external_id=payload.external_id, processing_started_at=None, next_attempt_at=None))
    if result.rowcount != 1:
        db.rollback(); raise HTTPException(409, "Publication is not owned by this worker")
    publication = db.query(Publication).filter(Publication.id == publication_id).first()
    channel = db.query(Channel).filter(Channel.id == publication.channel_id).first()
    if publication.content.status == "publishing": transition_content(db, publication.content, "published")
    if publication.source_draft_id:
        draft = db.query(PostDraft).filter(PostDraft.id == publication.source_draft_id).first()
        if draft: draft.status = "published"
    audit(db, channel.workspace_id, "publication", publication.id, "published")
    db.commit(); db.refresh(publication)
    return publication

@router.post("/publications/{publication_id}/fail", response_model=PublicationOut, dependencies=[Depends(require_service_token)])
def fail_publication(publication_id: int, payload: PublicationFail, db: Session = Depends(get_db)):
    publication = db.query(Publication).filter(Publication.id == publication_id).first()
    if not publication: raise HTTPException(404, "Publication not found")
    if publication.status != "processing" or publication.worker_id != payload.worker_id: raise HTTPException(409, "Publication is not owned by this worker")
    retry = payload.retry and publication.attempt_count < payload.max_attempts
    if retry:
        publication.status = "scheduled"; publication.next_attempt_at = datetime.utcnow() + timedelta(seconds=payload.retry_delay_seconds); publication.processing_started_at = None; action = "retry_scheduled"
        if publication.content.status == "publishing": transition_content(db, publication.content, "scheduled")
    else:
        publication.status = "failed"; publication.next_attempt_at = None; publication.processing_started_at = None; action = "failed"
        if publication.content.status == "publishing": transition_content(db, publication.content, "failed")
    publication.error_message = payload.error_message; publication.worker_id = None
    channel = db.query(Channel).filter(Channel.id == publication.channel_id).first()
    audit(db, channel.workspace_id, "publication", publication.id, action)
    db.commit(); db.refresh(publication)
    return publication
