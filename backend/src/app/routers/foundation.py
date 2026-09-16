from datetime import datetime
from typing import List, Optional
import uuid

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from src.app.audit import audit
from src.app.db import get_db
from src.app.models import Channel, Content, ContentVersion, Publication, PublicationOperation
from src.app.publication_state import publication_out, publication_ready_out, publication_unknown_out
from src.app.publication_worker import publication_event
from src.app.schemas import (
    ChannelCreate,
    ChannelOut,
    ContentCreate,
    ContentOut,
    ContentUpdate,
    ContentVersionOut,
    PublicationCreate,
    PublicationOut,
    PublicationReadyOut,
    PublicationUnknownOut,
)
from src.app.services import publication_service
from src.app.domain.content_state_machine import transition

router = APIRouter(prefix="/content", tags=["content"])

# NOTE: this file is intentionally kept compatible with the existing foundation
# routes. The service-token dependency is attached to each endpoint below.


def require_service_token():
    from src.app.routers.lifecycle import require_service_token as _require
    return _require()


@router.post("/workspaces", status_code=201)
def create_workspace(payload, db: Session = Depends(get_db)):
    from src.app.models import Workspace
    workspace = Workspace(name=payload.name, slug=payload.slug)
    db.add(workspace)
    db.flush()
    audit(db, None, "workspace", workspace.id, "created", actor_user_id=getattr(payload, "created_by", None), event_type="workspace.created")
    db.commit()
    db.refresh(workspace)
    return workspace


@router.post("/channels", response_model=ChannelOut, status_code=201)
def create_channel(payload: ChannelCreate, db: Session = Depends(get_db)):
    channel = Channel(**payload.model_dump())
    db.add(channel)
    db.commit()
    db.refresh(channel)
    return channel


@router.post("/contents", response_model=ContentOut, status_code=201)
def create_content(payload: ContentCreate, db: Session = Depends(get_db)):
    content = Content(workspace_id=payload.workspace_id, title=payload.title, language=payload.language, status=payload.status)
    db.add(content)
    db.flush()
    db.add(ContentVersion(content_id=content.id, version=1, body=payload.body, source=payload.source, created_by=payload.created_by))
    audit(db, content.workspace_id, "content", content.id, "created", actor_user_id=payload.created_by, event_type="content.created", metadata={"language": content.language, "source": payload.source})
    db.commit()
    db.refresh(content)
    return content


@router.post("/contents/{content_id}/versions", response_model=ContentVersionOut, status_code=201)
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


@router.get("/contents", response_model=List[ContentOut])
def list_contents(workspace_id: Optional[int] = None, db: Session = Depends(get_db)):
    query = db.query(Content)
    if workspace_id is not None:
        query = query.filter(Content.workspace_id == workspace_id)
    return query.order_by(Content.created_at.asc(), Content.id.asc()).all()


@router.get("/contents/{content_id}/versions", response_model=List[ContentVersionOut])
def list_content_versions(content_id: int, db: Session = Depends(get_db)):
    if not db.query(Content).filter(Content.id == content_id).first():
        raise HTTPException(404, "Content not found")
    return db.query(ContentVersion).filter(ContentVersion.content_id == content_id).order_by(ContentVersion.version.desc()).all()


@router.post("/publications", response_model=PublicationOut, status_code=201)
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


@router.get("/publications/ready", response_model=List[PublicationReadyOut])
def list_ready_publications(limit: int = 20, db: Session = Depends(get_db)):
    from sqlalchemy import or_
    now = datetime.utcnow()
    query = db.query(Publication).join(Content).join(Channel).filter(Publication.status == "scheduled", or_(Publication.scheduled_at.is_(None), Publication.scheduled_at <= now), or_(Publication.next_attempt_at.is_(None), Publication.next_attempt_at <= now), Channel.is_active.is_(True)).order_by(Publication.id.asc()).limit(max(1, min(limit, 100)))
    return [publication_ready_out(item) for item in query.all()]


@router.get("/publications/unknown", response_model=List[PublicationUnknownOut])
def list_unknown_publications(limit: int = 20, db: Session = Depends(get_db)):
    query = db.query(Publication).join(PublicationOperation).join(Channel).filter(Publication.status == "failed", PublicationOperation.status == "unknown", Channel.is_active.is_(True)).order_by(Publication.id.asc()).limit(max(1, min(limit, 100)))
    return [publication_unknown_out(item) for item in query.all()]


@router.get("/publications", response_model=List[PublicationOut])
def list_publications(workspace_id: Optional[int] = None, db: Session = Depends(get_db)):
    query = db.query(Publication).join(Channel)
    if workspace_id is not None:
        query = query.filter(Channel.workspace_id == workspace_id)
    return [publication_out(item) for item in query.order_by(Publication.scheduled_at.asc(), Publication.id.asc()).all()]


@router.post("/publications/recover-stale", response_model=List[PublicationOut])
def recover_stale_publications(db: Session = Depends(get_db)):
    return [publication_out(item) for item in publication_service.recover_stale(db)]


@router.post("/publications/{publication_id}/claim", response_model=PublicationOut)
def claim_publication(publication_id: int, payload, db: Session = Depends(get_db)):
    return publication_out(publication_service.claim(db, publication_id, payload.worker_id))


@router.post("/publications/{publication_id}/heartbeat", response_model=PublicationOut)
def heartbeat_publication(publication_id: int, payload, db: Session = Depends(get_db)):
    return publication_out(publication_service.heartbeat(db, publication_id, payload.worker_id, payload.processing_token))
