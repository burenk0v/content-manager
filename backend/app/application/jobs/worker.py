"""Generic durable-job worker.

This loop knows how to claim/complete/fail jobs, but knows nothing about the
business domain or external provider SDKs. It is intentionally small so the
same execution model can back AI generation, publication and future jobs.
"""

import asyncio
import logging
from datetime import UTC, datetime, timedelta
from uuid import uuid4

from .contracts import JobContext, JobRepository
from .registry import JobHandlerRegistry

logger = logging.getLogger(__name__)


class JobWorker:
    def __init__(
        self,
        repository: JobRepository,
        registry: JobHandlerRegistry,
        *,
        worker_id: str | None = None,
        poll_interval: float = 1.0,
        retry_delay: float = 5.0,
    ) -> None:
        if poll_interval <= 0:
            raise ValueError("poll_interval must be positive")
        self.repository = repository
        self.registry = registry
        self.worker_id = worker_id or f"worker-{uuid4()}"
        self.poll_interval = poll_interval
        self.retry_delay = retry_delay

    async def run_once(self, *, limit: int = 1) -> int:
        jobs = await self.repository.claim(worker_id=self.worker_id, limit=limit)
        for job in jobs:
            await self._execute(job)
        return len(jobs)

    async def _execute(self, job: dict) -> None:
        job_id = str(job["id"])
        try:
            handler = self.registry.get(str(job["job_type"]))
            context = JobContext(
                job_id=job_id,
                correlation_id=str(job.get("correlation_id") or job_id),
                attempt=int(job.get("attempt", 1)),
            )
            result = await handler.handle(dict(job.get("payload") or {}), context)
            await self.repository.complete(job_id, result=result)
        except Exception as exc:  # noqa: BLE001 - worker boundary must persist failures
            logger.exception("job execution failed", extra={"job_id": job_id})
            retry_at = datetime.now(UTC) + timedelta(seconds=self.retry_delay)
            await self.repository.fail(job_id, error=str(exc), retry_at=retry_at)

    async def run_forever(self, *, stop_event: asyncio.Event | None = None) -> None:
        while stop_event is None or not stop_event.is_set():
            processed = await self.run_once()
            if not processed:
                await asyncio.sleep(self.poll_interval)
