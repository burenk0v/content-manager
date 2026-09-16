from datetime import datetime
from typing import Optional
import os

from fastapi import APIRouter, Depends, Header, HTTPException, status
from pydantic import BaseModel, ConfigDict
from sqlalchemy.orm import Session

from src.app.db import get_db
from src.app.models import AuditLog

router = APIRouter()


class AuditEventOut(BaseModel):
    id: int
    workspace_id: Optional[int]
    actor_user_id: Optional[int]
    entity_type: str
    entity_id: Optional[int]
    action: str
    event_type: Optional[str]
    request_id: Optional[str]
    metadata: Optional[dict]
    created_at: datetime
    model_config = ConfigDict(from_attributes=True)


def require_service_token(x_service_token: Optional[str] = Header(None)) -> None:
    expected = os.environ.get("SERVICE_ACCOUNT_TOKEN")
    if not expected or x_service_token != expected:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid service token")


@router.get("", response_model=list[AuditEventOut], dependencies=[Depends(require_service_token)])
def list_audit_events(
    workspace_id: Optional[int] = None,
    entity_type: Optional[str] = None,
    entity_id: Optional[int] = None,
    event_type: Optional[str] = None,
    request_id: Optional[str] = None,
    limit: int = 50,
    db: Session = Depends(get_db),
):
    query = db.query(AuditLog)
    if workspace_id is not None:
        query = query.filter(AuditLog.workspace_id == workspace_id)
    if entity_type is not None:
        query = query.filter(AuditLog.entity_type == entity_type)
    if entity_id is not None:
        query = query.filter(AuditLog.entity_id == entity_id)
    if event_type is not None:
        query = query.filter(AuditLog.event_type == event_type)
    if request_id is not None:
        query = query.filter(AuditLog.request_id == request_id)
    return query.order_by(AuditLog.id.desc()).limit(max(1, min(limit, 200))).all()
