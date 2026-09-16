from datetime import datetime
from typing import Optional
import hmac
import os

from fastapi import APIRouter, Depends, Header, HTTPException, status
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from src.app.audit import audit
from src.app.db import get_db
from src.app.domain.content_state_machine import InvalidContentTransition, allowed_transitions, transition
from src.app.models import Content, Publication

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


def require_service_token(x_service_token: Optional[str] = Header(None)) -> None:
    expected = os.environ.get("SERVICE_ACCOUNT_TOKEN")
    if not expected or not x_service_token or not hmac.compare_digest(x_service_token, expected):
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid service token")


@router.get("/contents/{content_id}/workflow", response_model=WorkflowSnapshot, dependencies=[Depends(require_service_token)])
def workflow_snapshot(content_id: int, db: Session = Depends(get_db)) -> WorkflowSnapshot:
    content = db.query(Content).filter(Content.id == content_id).first()
    if not content:
        raise HTTPException(404, "Content not found")

    counts: dict[str, int] = {}
    for publication in db.query(Publication).filter(Publication.content_id == content.id).all():
        counts[publication.status] = counts.get(publication.status, 0) + 1

    version = content.current_version
    return WorkflowSnapshot(
        id=content.id,
        status=content.status,
        allowed_transitions=list(allowed_transitions(content.status)),
        current_version_id=version.id,
        current_version=version.version,
        publication_counts=counts,
        updated_at=content.updated_at,
    )


@router.post("/contents/bulk-transition", response_model=list[BulkTransitionOut], dependencies=[Depends(require_service_token)])
def bulk_transition(payload: BulkTransitionRequest, db: Session = Depends(get_db)) -> list[BulkTransitionOut]:
    ids = [item.content_id for item in payload.items]
    if len(ids) != len(set(ids)):
        raise HTTPException(422, "content_id values must be unique")

    contents = {content.id: content for content in db.query(Content).filter(Content.id.in_(ids)).all()}
    missing = [content_id for content_id in ids if content_id not in contents]
    if missing:
        raise HTTPException(404, f"Content not found: {missing[0]}")

    changes: list[BulkTransitionOut] = []
    try:
        for item in payload.items:
            content = contents[item.content_id]
            previous = content.status
            transition(previous, item.status)
            if previous == item.status:
                changes.append(BulkTransitionOut(content_id=content.id, previous_status=previous, status=previous))
                continue
            content.status = item.status
            content.updated_at = datetime.utcnow()
            audit(
                db,
                content.workspace_id,
                "content",
                content.id,
                "status_changed",
                actor_user_id=payload.actor_user_id,
                event_type="content.status_changed",
                metadata={"from": previous, "to": item.status, "bulk": True},
            )
            changes.append(BulkTransitionOut(content_id=content.id, previous_status=previous, status=item.status))
    except InvalidContentTransition as exc:
        db.rollback()
        raise HTTPException(409, detail=str(exc)) from exc

    db.commit()
    return changes
