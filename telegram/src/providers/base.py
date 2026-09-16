from dataclasses import dataclass
from typing import Protocol


@dataclass(frozen=True)
class PublicationContext:
    publication_id: int
    idempotency_key: str
    channel_external_id: str
    content_body: str


@dataclass(frozen=True)
class PublicationResult:
    external_id: str
    message_count: int


class AmbiguousPublicationError(RuntimeError):
    """The provider may have accepted the publication but its outcome is unknown."""


class Publisher(Protocol):
    supports_idempotency: bool

    async def publish(self, context: PublicationContext) -> PublicationResult:
        """Publish content and return the provider's external identifier."""
