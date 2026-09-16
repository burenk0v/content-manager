from datetime import datetime
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy.orm import Session

from src.app.db import get_db
from src.app.routers.foundation import require_service_token
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
