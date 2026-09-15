from sqlalchemy.orm import Session

from src.app.content_lifecycle import transition_or_raise
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

    transition_or_raise(content.status, target)
    previous = content.status
    content.status = target
    from datetime import datetime
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
