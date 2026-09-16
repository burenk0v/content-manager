from __future__ import annotations

from contextvars import ContextVar
from typing import Any

from sqlalchemy.orm import Session

from src.app.models import AuditLog


_request_id: ContextVar[str | None] = ContextVar("audit_request_id", default=None)


def set_request_id(request_id: str) -> None:
    _request_id.set(request_id)


def get_request_id() -> str | None:
    return _request_id.get()


def audit(
    db: Session,
    workspace_id: int | None,
    entity_type: str,
    entity_id: int | None,
    action: str,
    *,
    actor_user_id: int | None = None,
    event_type: str | None = None,
    metadata: dict[str, Any] | None = None,
) -> AuditLog:
    event = AuditLog(
        workspace_id=workspace_id,
        actor_user_id=actor_user_id,
        entity_type=entity_type,
        entity_id=entity_id,
        action=action,
        event_type=event_type or action,
        request_id=get_request_id(),
        metadata_json=metadata,
    )
    db.add(event)
    return event
