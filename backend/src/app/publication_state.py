from datetime import datetime

from sqlalchemy.orm import Session

from src.app.domain.content_state_machine import transition
from src.app.models import AuditLog, Content, Publication


def sync_content_status(db: Session, content: Content) -> str:
    """Reconcile content lifecycle state with all of its channel publications."""
    publications = db.query(Publication).filter(Publication.content_id == content.id).all()
    if not publications:
        return content.status

    statuses = {publication.status for publication in publications}
    if statuses and statuses.issubset({"published"}):
        target = "published"
    elif "processing" in statuses:
        target = "publishing"
    elif "scheduled" in statuses:
        target = "scheduled"
    elif "failed" in statuses:
        target = "failed"
    else:
        return content.status

    if content.status == target:
        return target

    previous = content.status
    if target == "published" and previous == "failed":
        # The publication records are the source of truth for the aggregate state.
        # Reconciliation may discover a successful provider delivery after the
        # publication had been marked failed because its outcome was ambiguous.
        content.status = target
    else:
        transition(previous, target)
        content.status = target

    content.updated_at = datetime.utcnow()
    db.add(
        AuditLog(
            workspace_id=content.workspace_id,
            entity_type="content",
            entity_id=content.id,
            action="status_changed",
            metadata_json={"from": previous, "to": target, "reason": "publication_state_sync"},
        )
    )
    return target
