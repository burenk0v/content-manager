"""Ports for external systems.

Domain/application code imports these protocols; concrete SDK clients belong
in sibling adapter modules and are wired in the composition root.
"""

from dataclasses import dataclass
from typing import Any, Protocol


@dataclass(frozen=True, slots=True)
class GenerationRequest:
    prompt: str
    model: str | None = None
    parameters: dict[str, Any] | None = None


@dataclass(frozen=True, slots=True)
class GenerationResult:
    text: str
    provider: str
    model: str | None = None
    usage: dict[str, Any] | None = None
    raw: dict[str, Any] | None = None


class GenerationProvider(Protocol):
    async def generate(self, request: GenerationRequest) -> GenerationResult:
        """Generate content without leaking provider-specific types upward."""


@dataclass(frozen=True, slots=True)
class PublicationRequest:
    external_channel_id: str
    text: str
    idempotency_key: str
    media: tuple[str, ...] = ()


@dataclass(frozen=True, slots=True)
class PublicationResult:
    provider: str
    external_publication_id: str
    url: str | None = None
    raw: dict[str, Any] | None = None


class PublicationProvider(Protocol):
    async def publish(self, request: PublicationRequest) -> PublicationResult:
        """Publish through an external channel adapter."""

    async def reconcile(self, external_publication_id: str) -> PublicationResult:
        """Read provider state for recovery/reconciliation."""
