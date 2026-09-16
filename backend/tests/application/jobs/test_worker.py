from datetime import UTC, datetime

import pytest

from app.application.jobs.contracts import JobContext
from app.application.jobs.registry import JobHandlerRegistry
from app.application.jobs.worker import JobWorker


class InMemoryJobs:
    def __init__(self, jobs):
        self.jobs = jobs
        self.completed = []
        self.failed = []

    async def enqueue(self, *args, **kwargs):
        raise NotImplementedError

    async def claim(self, *, worker_id, limit=1):
        claimed, self.jobs = self.jobs[:limit], self.jobs[limit:]
        return claimed

    async def complete(self, job_id, *, result=None):
        self.completed.append((job_id, result))

    async def fail(self, job_id, *, error, retry_at):
        self.failed.append((job_id, error, retry_at))


@pytest.mark.asyncio
async def test_worker_dispatches_registered_handler():
    jobs = InMemoryJobs(
        [{"id": "1", "job_type": "demo", "payload": {"value": 42}, "attempt": 1}]
    )
    seen = []

    class Handler:
        async def handle(self, payload, context: JobContext):
            seen.append((payload, context.job_id))
            return {"ok": True}

    registry = JobHandlerRegistry({"demo": Handler()})
    worker = JobWorker(jobs, registry)

    assert await worker.run_once() == 1
    assert seen == [({"value": 42}, "1")]
    assert jobs.completed == [("1", {"ok": True})]
    assert jobs.failed == []


@pytest.mark.asyncio
async def test_worker_persists_handler_failure_for_retry():
    jobs = InMemoryJobs(
        [{"id": "2", "job_type": "demo", "payload": {}, "attempt": 2}]
    )

    class Handler:
        async def handle(self, payload, context):
            raise RuntimeError("provider unavailable")

    worker = JobWorker(jobs, JobHandlerRegistry({"demo": Handler()}), retry_delay=0)

    assert await worker.run_once() == 1
    assert jobs.completed == []
    assert jobs.failed[0][0:2] == ("2", "provider unavailable")
    assert isinstance(jobs.failed[0][2], datetime)
    assert jobs.failed[0][2].tzinfo == UTC
