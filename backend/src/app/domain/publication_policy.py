from dataclasses import dataclass
from datetime import datetime


@dataclass(frozen=True)
class PublicationDecision:
    allowed: bool
    reason: str


def can_publish_content(status: str, scheduled_at: datetime | None, now: datetime) -> PublicationDecision:
    if status != "approved":
        return PublicationDecision(False, "Content must be approved before publication")
    if scheduled_at is not None and scheduled_at > now:
        return PublicationDecision(False, "Publication is scheduled for a future time")
    return PublicationDecision(True, "Content is eligible for publication")
