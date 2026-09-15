import os
from datetime import datetime
from typing import List, Optional

from fastapi import APIRouter, Depends, Header, HTTPException, status
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from src.app.db import get_db
from src.app.models import AuditLog, Channel, Content, ContentVersion, Publication, Workspace

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
    status: str
    scheduled_at: Optional[datetime]
    published_at: Optional[datetime]
    external_id: Optional[str]
    idempotency_key: str
    error_message: Optional[str]
    created_at: datetime
    class Config:
        orm_mode = True


def require_service_token(x_service_token: Optional[str] = Header(None)) -> None:
    expected = os.environ.get("SERVICE_ACCOUNT_TOKEN")
    if not expected or x_service_token != expected:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid service token")


def audit(db: Session, workspace_id: int, entity_type: str, entity_id: int, action: str) -> None:
    db.add(AuditLog(workspace_id=workspace_id, entity_type=entity_type, entity_id=entity_id, action=action))


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
    publication = Publication(content_id=content.id, channel_id=channel.id, scheduled_at=payload.scheduled_at, idempotency_key=key, status="scheduled")
    db.add(publication); db.flush()
    audit(db, content.workspace_id, "publication", publication.id, "scheduled")
    db.commit(); db.refresh(publication)
    return publication

@router.get("/publications", response_model=List[PublicationOut], dependencies=[Depends(require_service_token)])
def list_publications(workspace_id: Optional[int] = None, db: Session = Depends(get_db)):
    query = db.query(Publication).join(Channel)
    if workspace_id is not None: query = query.filter(Channel.workspace_id == workspace_id)
    return query.order_by(Publication.scheduled_at.asc(), Publication.id.asc()).all()
