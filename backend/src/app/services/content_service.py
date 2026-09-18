from __future__ import annotations

from datetime import datetime

from sqlalchemy.orm import Session

from src.app.audit import audit
from src.app.domain.content_state_machine import InvalidContentTransition, allowed_transitions, transition
from src.app.models import Content, Publication


class ContentNotFound(Exception):
    pass


class ContentTransitionConflict(Exception):
    pass


def get_content(db: Session, content_id: int) -> Content:
    content = db.query(Content).filter(Content.id == content_id).first()
    if not content:
        raise ContentNotFound
    return content


def get_allowed_transitions(db: Session, content_id: int) -> tuple[str, list[str]]:
    content = get_content(db, content_id)
    return content.status, list(allowed_transitions(content.status))


def transition_content(
    db: Session,
    content_id: int,
    target_status: str,
    *,
    actor_user_id: int | None = None,
) -> Content:
    content = get_content(db, content_id)
    previous_status = content.status
    try:
        next_status = transition(previous_status, target_status)
    except InvalidContentTransition as exc:
        raise ContentTransitionConflict(str(exc)) from exc

    if previous_status == next_status:
        return content

    content.status = next_status
    content.updated_at = datetime.utcnow()
    audit(
        db,
        content.workspace_id,
        "content",
        content.id,
        "status_changed",
        actor_user_id=actor_user_id,
        event_type="content.status_changed",
        metadata={"from": previous_status, "to": next_status},
    )
    return content


def get_workflow_snapshot(db: Session, content_id: int) -> dict:
    content = get_content(db, content_id)
    counts: dict[str, int] = {}
    for publication in db.query(Publication).filter(Publication.content_id == content.id).all():
        counts[publication.status] = counts.get(publication.status, 0) + 1

    version = content.current_version
    return {
        "id": content.id,
        "status": content.status,
        "allowed_transitions": list(allowed_transitions(content.status)),
        "current_version_id": version.id,
        "current_version": version.version,
        "publication_counts": counts,
        "updated_at": content.updated_at,
    }


def bulk_transition(
    db: Session,
    items: list[tuple[int, str]],
    *,
    actor_user_id: int | None = None,
) -> list[dict]:
    ids = [content_id for content_id, _ in items]
    contents = {content.id: content for content in db.query(Content).filter(Content.id.in_(ids)).with_for_update().all()}
    missing = [content_id for content_id in ids if content_id not in contents]
    if missing:
        raise ContentNotFound(missing[0])

    changes: list[dict] = []
    try:
        for content_id, target_status in items:
            content = contents[content_id]
            previous = content.status
            transition(previous, target_status)
            if previous != target_status:
                content.status = target_status
                content.updated_at = datetime.utcnow()
                audit(
                    db,
                    content.workspace_id,
                    "content",
                    content.id,
                    "status_changed",
                    actor_user_id=actor_user_id,
                    event_type="content.status_changed",
                    metadata={"from": previous, "to": target_status, "bulk": True},
                )
            changes.append({"content_id": content.id, "previous_status": previous, "status": content.status})
    except InvalidContentTransition as exc:
        raise ContentTransitionConflict(str(exc)) from exc
    return changes
