from datetime import datetime
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from src.app.db import get_db
from src.app.routers.foundation import require_service_token
from src.app.services.content_service import (
    ContentNotFound,
    ContentTransitionConflict,
    bulk_transition as bulk_transition_service,
    get_workflow_snapshot,
)

router = APIRouter()


class BulkTransitionItem(BaseModel):
    content_id: int = Field(..., gt=0)
    status: str = Field(..., min_length=1, max_length=30)


class BulkTransitionRequest(BaseModel):
    items: list[BulkTransitionItem] = Field(..., min_length=1, max_length=100)
    actor_user_id: Optional[int] = None


class WorkflowSnapshot(BaseModel):
    id: int
    status: str
    allowed_transitions: list[str]
    current_version_id: int
    current_version: int
    publication_counts: dict[str, int]
    updated_at: datetime


class BulkTransitionOut(BaseModel):
    content_id: int
    previous_status: str
    status: str


@router.get("/contents/{content_id}/workflow", response_model=WorkflowSnapshot, dependencies=[Depends(require_service_token)])
def workflow_snapshot(content_id: int, db: Session = Depends(get_db)) -> WorkflowSnapshot:
    try:
        return WorkflowSnapshot(**get_workflow_snapshot(db, content_id))
    except ContentNotFound as exc:
        raise HTTPException(404, "Content not found") from exc


@router.post("/contents/bulk-transition", response_model=list[BulkTransitionOut], dependencies=[Depends(require_service_token)])
def bulk_transition(payload: BulkTransitionRequest, db: Session = Depends(get_db)) -> list[BulkTransitionOut]:
    ids = [item.content_id for item in payload.items]
    if len(ids) != len(set(ids)):
        raise HTTPException(422, "content_id values must be unique")

    try:
        changes = bulk_transition_service(
            db,
            [(item.content_id, item.status) for item in payload.items],
            actor_user_id=payload.actor_user_id,
        )
    except ContentNotFound as exc:
        raise HTTPException(404, f"Content not found: {exc.args[0]}") from exc
    except ContentTransitionConflict as exc:
        db.rollback()
        raise HTTPException(409, detail=str(exc)) from exc

    db.commit()
    return [BulkTransitionOut(**change) for change in changes]
