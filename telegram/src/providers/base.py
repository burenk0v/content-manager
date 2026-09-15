from dataclasses import dataclass
from typing import Protocol


@dataclass(frozen=True)
class PublicationContext:
    publication_id: int
    channel_external_id: str
    content_body: str


@dataclass(frozen=True)
class PublicationResult:
    external_id: str
    message_count: int


class Publisher(Protocol):
    async def publish(self, context: PublicationContext) -> PublicationResult:
        """Publish content and return the provider's external identifier."""
