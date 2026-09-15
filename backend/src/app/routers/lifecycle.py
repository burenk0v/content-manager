from datetime import datetime
from typing import Optional

import os
from fastapi import APIRouter, Depends, Header, HTTPException, status
from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy.orm import Session

from src.app.content_lifecycle import CONTENT_TRANSITIONS, transition_or_raise
from src.app.db import get_db
from src.app.models import AuditLog, Content

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


def require_service_token(x_service_token: Optional[str] = Header(None)) -> None:
    expected = os.environ.get("SERVICE_ACCOUNT_TOKEN")
    if not expected or x_service_token != expected:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid service token")


@router.get("/contents/{content_id}/transitions", dependencies=[Depends(require_service_token)])
def list_transitions(content_id: int, db: Session = Depends(get_db)):
    content = db.query(Content).filter(Content.id == content_id).first()
    if not content:
        raise HTTPException(404, "Content not found")
    return {"status": content.status, "allowed": sorted(CONTENT_TRANSITIONS.get(content.status, frozenset()))}


@router.post("/contents/{content_id}/transition", response_model=ContentTransitionOut, dependencies=[Depends(require_service_token)])
def transition_content(content_id: int, payload: ContentTransition, db: Session = Depends(get_db)):
    content = db.query(Content).filter(Content.id == content_id).first()
    if not content:
        raise HTTPException(404, "Content not found")

    previous_status = content.status
    transition_or_raise(previous_status, payload.status)
    if previous_status == payload.status:
        return ContentTransitionOut(id=content.id, previous_status=previous_status, status=content.status, updated_at=content.updated_at)

    content.status = payload.status
    content.updated_at = datetime.utcnow()
    db.add(AuditLog(
        workspace_id=content.workspace_id,
        actor_user_id=payload.actor_user_id,
        entity_type="content",
        entity_id=content.id,
        action="status_changed",
        metadata_json={"from": previous_status, "to": payload.status},
    ))
    db.commit()
    db.refresh(content)
    return ContentTransitionOut(
        id=content.id,
        previous_status=previous_status,
        status=content.status,
        updated_at=content.updated_at,
    )
