"""Stable contracts for asynchronous application work.

Workers should depend on these contracts rather than on provider SDKs or ORM models.
"""

from dataclasses import dataclass
from datetime import datetime
from typing import Any, Protocol


@dataclass(frozen=True, slots=True)
class JobContext:
    """Execution metadata propagated to adapters and observability."""

    job_id: str
    correlation_id: str
    attempt: int = 1


class JobHandler(Protocol):
    """Port implemented by application-level job handlers."""

    async def handle(self, payload: dict[str, Any], context: JobContext) -> Any:
        """Execute one idempotent unit of application work."""


class JobRepository(Protocol):
    """Persistence port for durable jobs.

    The concrete implementation owns transactions, claiming/leases and retries.
    """

    async def enqueue(
        self,
        job_type: str,
        payload: dict[str, Any],
        *,
        idempotency_key: str,
        run_at: datetime | None = None,
    ) -> str:
        """Persist a job and return its identifier."""

    async def claim(self, *, worker_id: str, limit: int = 1) -> list[dict[str, Any]]:
        """Atomically claim ready jobs for a worker."""

    async def complete(self, job_id: str, *, result: Any = None) -> None:
        """Mark a claimed job as successfully completed."""

    async def fail(self, job_id: str, *, error: str, retry_at: datetime | None) -> None:
        """Record failure and either schedule a retry or make it terminal."""
