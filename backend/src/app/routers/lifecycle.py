from datetime import datetime
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy.orm import Session

from src.app.db import get_db
from src.app.routers.foundation import require_service_token
from src.app.models import Content, ContentProfile
from src.app.audit import audit
from src.app.services.content_service import (
    ContentNotFound,
    ContentTransitionConflict,
    get_allowed_transitions,
    transition_content as transition_content_service,
)

router = APIRouter()


class ContentTransition(BaseModel):
    status: str = Field(..., min_length=1, max_length=30)
    actor_user_id: Optional[int] = None


class ContentTransitionOut(BaseModel):
    id: int
    previous_status: str
    status: str
    updated_at: datetime

    model_config = ConfigDict(from_attributes=True)


class ContentActionReason(BaseModel):
    reason: str = Field(..., min_length=1, max_length=1000)


@router.get("/contents/{content_id}/transitions", dependencies=[Depends(require_service_token)])
def list_transitions(content_id: int, db: Session = Depends(get_db)):
    try:
        current_status, allowed = get_allowed_transitions(db, content_id)
    except ContentNotFound as exc:
        raise HTTPException(404, "Content not found") from exc
    return {"status": current_status, "allowed": allowed}


@router.post("/contents/{content_id}/transition", response_model=ContentTransitionOut, dependencies=[Depends(require_service_token)])
def transition_content(content_id: int, payload: ContentTransition, db: Session = Depends(get_db)):
    try:
        previous_status = get_allowed_transitions(db, content_id)[0]
        content = transition_content_service(
            db,
            content_id,
            payload.status,
            actor_user_id=payload.actor_user_id,
        )
    except ContentNotFound as exc:
        raise HTTPException(404, "Content not found") from exc
    except ContentTransitionConflict as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc

    db.commit()
    db.refresh(content)
    return ContentTransitionOut(
        id=content.id,
        previous_status=previous_status,
        status=content.status,
        updated_at=content.updated_at,
    )


@router.post("/contents/{content_id}/reject", response_model=ContentTransitionOut, dependencies=[Depends(require_service_token)])
def reject_content(content_id: int, payload: ContentActionReason, db: Session = Depends(get_db)):
    content = db.query(Content).filter(Content.id == content_id).with_for_update().first()
    if not content:
        raise HTTPException(404, "Content not found")
    previous_status = content.status
    if content.status == "review":
        transition_content_service(db, content_id, "draft")
        content = db.query(Content).filter(Content.id == content_id).first()
        audit(
            db,
            content.workspace_id,
            "content",
            content.id,
            "rejected",
            event_type="content.rejected",
            metadata={"reason": payload.reason.strip()},
        )
    elif content.status != "draft":
        raise HTTPException(409, "Content can only be rejected from review or draft")
    db.commit()
    db.refresh(content)
    return ContentTransitionOut(
        id=content.id,
        previous_status=previous_status,
        status=content.status,
        updated_at=content.updated_at,
    )


@router.post("/contents/{content_id}/regenerate", response_model=ContentTransitionOut, dependencies=[Depends(require_service_token)])
def regenerate_content(content_id: int, payload: ContentActionReason | None = None, db: Session = Depends(get_db)):
    content = db.query(Content).filter(Content.id == content_id).with_for_update().first()
    if not content:
        raise HTTPException(404, "Content not found")
    if not content.profile_id:
        raise HTTPException(409, "Content is not attached to a profile")
    profile = db.query(ContentProfile).filter(ContentProfile.id == content.profile_id).with_for_update().first()
    if not profile or not profile.is_active:
        raise HTTPException(409, "Content profile is unavailable")

    previous_status = content.status
    if content.status == "review":
        transition_content_service(db, content_id, "draft")
        content = db.query(Content).filter(Content.id == content_id).first()
    elif content.status != "draft":
        raise HTTPException(409, "Content can only be regenerated from review or draft")

    profile.regeneration_requested = True
    profile.updated_at = datetime.utcnow()
    audit(
        db,
        content.workspace_id,
        "content",
        content.id,
        "regeneration_requested",
        event_type="content.regeneration_requested",
        metadata={"reason": (payload.reason.strip() if payload else "Telegram operator requested regeneration")},
    )
    db.commit()
    db.refresh(content)
    return ContentTransitionOut(
        id=content.id,
        previous_status=previous_status,
        status=content.status,
        updated_at=content.updated_at,
    )
