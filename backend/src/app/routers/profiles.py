from datetime import datetime
from typing import List, Optional

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy.orm import Session

from src.app.audit import audit
from src.app.db import get_db
from src.app.models import Channel, ContentProfile, Workspace
from src.app.routers.foundation import require_service_token

router = APIRouter()


class ContentProfileCreate(BaseModel):
    workspace_id: int
    channel_id: int
    name: str = Field(..., min_length=1, max_length=200)
    language: str = Field("en", min_length=2, max_length=10)
    topic_niche: Optional[str] = Field(None, max_length=4000)
    tone: Optional[str] = Field(None, max_length=500)
    content_format: Optional[str] = Field(None, max_length=500)
    rules: Optional[str] = Field(None, max_length=8000)
    timezone: str = Field("UTC", min_length=1, max_length=100)
    schedule_type: str = Field("daily", pattern="^(interval|daily)$")
    schedule_value: str = Field(..., min_length=1, max_length=100)
    is_active: bool = True


class ContentProfileUpdate(BaseModel):
    workspace_id: Optional[int] = None
    channel_id: Optional[int] = None
    name: Optional[str] = Field(None, min_length=1, max_length=200)
    language: Optional[str] = Field(None, min_length=2, max_length=10)
    topic_niche: Optional[str] = Field(None, max_length=4000)
    tone: Optional[str] = Field(None, max_length=500)
    content_format: Optional[str] = Field(None, max_length=500)
    rules: Optional[str] = Field(None, max_length=8000)
    timezone: Optional[str] = Field(None, min_length=1, max_length=100)
    schedule_type: Optional[str] = Field(None, pattern="^(interval|daily)$")
    schedule_value: Optional[str] = Field(None, min_length=1, max_length=100)
    is_active: Optional[bool] = None


class ContentProfileOut(ContentProfileCreate):
    id: int
    last_run: Optional[datetime]
    regeneration_requested: bool
    created_at: datetime
    updated_at: datetime
    channel_external_id: str
    channel_name: Optional[str]
    model_config = ConfigDict(from_attributes=True)


def profile_out(profile: ContentProfile) -> ContentProfileOut:
    return ContentProfileOut(
        id=profile.id,
        workspace_id=profile.workspace_id,
        channel_id=profile.channel_id,
        name=profile.name,
        language=profile.language,
        topic_niche=profile.topic_niche,
        tone=profile.tone,
        content_format=profile.content_format,
        rules=profile.rules,
        timezone=profile.timezone,
        schedule_type=profile.schedule_type,
        schedule_value=profile.schedule_value,
        is_active=profile.is_active,
        last_run=profile.last_run,
        regeneration_requested=profile.regeneration_requested,
        created_at=profile.created_at,
        updated_at=profile.updated_at,
        channel_external_id=profile.channel.external_id,
        channel_name=profile.channel.name,
    )


def validate_refs(db: Session, workspace_id: int, channel_id: int) -> Channel:
    if not db.query(Workspace).filter(Workspace.id == workspace_id).first():
        raise HTTPException(404, "Workspace not found")
    channel = db.query(Channel).filter(Channel.id == channel_id).first()
    if not channel:
        raise HTTPException(404, "Channel not found")
    if channel.workspace_id != workspace_id:
        raise HTTPException(400, "Channel must belong to the workspace")
    return channel


@router.post("/profiles", response_model=ContentProfileOut, status_code=201, dependencies=[Depends(require_service_token)])
def create_profile(payload: ContentProfileCreate, db: Session = Depends(get_db)):
    validate_refs(db, payload.workspace_id, payload.channel_id)
    profile = ContentProfile(**payload.model_dump())
    db.add(profile)
    try:
        db.flush()
    except Exception:
        db.rollback()
        raise HTTPException(409, "Content profile already exists")
    audit(db, profile.workspace_id, "content_profile", profile.id, "created", event_type="content_profile.created")
    db.commit()
    db.refresh(profile)
    return profile_out(profile)


@router.get("/profiles", response_model=List[ContentProfileOut], dependencies=[Depends(require_service_token)])
def list_profiles(workspace_id: Optional[int] = None, channel_id: Optional[int] = None, db: Session = Depends(get_db)):
    query = db.query(ContentProfile)
    if workspace_id is not None:
        query = query.filter(ContentProfile.workspace_id == workspace_id)
    if channel_id is not None:
        query = query.filter(ContentProfile.channel_id == channel_id)
    return [profile_out(item) for item in query.order_by(ContentProfile.created_at.desc(), ContentProfile.id.desc()).all()]


@router.get("/profiles/{profile_id}", response_model=ContentProfileOut, dependencies=[Depends(require_service_token)])
def get_profile(profile_id: int, db: Session = Depends(get_db)):
    profile = db.query(ContentProfile).filter(ContentProfile.id == profile_id).first()
    if not profile:
        raise HTTPException(404, "Content profile not found")
    return profile_out(profile)


@router.put("/profiles/{profile_id}", response_model=ContentProfileOut, dependencies=[Depends(require_service_token)])
def update_profile(profile_id: int, payload: ContentProfileUpdate, db: Session = Depends(get_db)):
    profile = db.query(ContentProfile).filter(ContentProfile.id == profile_id).first()
    if not profile:
        raise HTTPException(404, "Content profile not found")
    values = payload.model_dump(exclude_unset=True)
    workspace_id = values.get("workspace_id", profile.workspace_id)
    channel_id = values.get("channel_id", profile.channel_id)
    validate_refs(db, workspace_id, channel_id)
    for key, value in values.items():
        setattr(profile, key, value)
    profile.updated_at = datetime.utcnow()
    audit(db, profile.workspace_id, "content_profile", profile.id, "updated", event_type="content_profile.updated")
    db.commit()
    db.refresh(profile)
    return profile_out(profile)


@router.delete("/profiles/{profile_id}", status_code=204, dependencies=[Depends(require_service_token)])
def delete_profile(profile_id: int, db: Session = Depends(get_db)):
    profile = db.query(ContentProfile).filter(ContentProfile.id == profile_id).first()
    if not profile:
        raise HTTPException(404, "Content profile not found")
    workspace_id = profile.workspace_id
    db.delete(profile)
    audit(db, workspace_id, "content_profile", profile_id, "deleted", event_type="content_profile.deleted")
    db.commit()


@router.post("/profiles/{profile_id}/regenerate", response_model=ContentProfileOut, dependencies=[Depends(require_service_token)])
def request_regeneration(profile_id: int, db: Session = Depends(get_db)):
    profile = db.query(ContentProfile).filter(ContentProfile.id == profile_id).first()
    if not profile:
        raise HTTPException(404, "Content profile not found")
    profile.regeneration_requested = True
    profile.updated_at = datetime.utcnow()
    audit(db, profile.workspace_id, "content_profile", profile.id, "regeneration_requested", event_type="content_profile.regeneration_requested")
    db.commit()
    db.refresh(profile)
    return profile_out(profile)
