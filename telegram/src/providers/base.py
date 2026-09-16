from dataclasses import dataclass
from typing import Literal, Protocol


@dataclass(frozen=True)
class PublicationContext:
    publication_id: int
    provider_operation_key: str
    channel_external_id: str
    content_body: str


@dataclass(frozen=True)
class PublicationResult:
    external_id: str
    message_count: int


@dataclass(frozen=True)
class ReconciliationResult:
    outcome: Literal["published", "not_published", "unknown"]
    external_id: str | None = None


class AmbiguousPublicationError(RuntimeError):
    """The provider may have accepted the publication but its outcome is unknown."""


class Publisher(Protocol):
    supports_idempotency: bool

    async def publish(self, context: PublicationContext) -> PublicationResult:
        """Publish content and return the provider's external identifier."""


class ProviderReconciler(Protocol):
    supports_reconciliation: bool

    async def reconcile(self, context: PublicationContext) -> ReconciliationResult:
        """Determine whether an ambiguous provider operation was delivered."""
