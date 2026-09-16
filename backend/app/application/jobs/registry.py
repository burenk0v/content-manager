"""Job handler registry.

The registry deliberately contains no provider-specific logic. Adapters are
registered at the composition root and invoked by their application handler.
"""

from collections.abc import Mapping

from .contracts import JobHandler


class JobHandlerRegistry:
    def __init__(self, handlers: Mapping[str, JobHandler] | None = None) -> None:
        self._handlers = dict(handlers or {})

    def register(self, job_type: str, handler: JobHandler) -> None:
        if job_type in self._handlers:
            raise ValueError(f"job handler already registered: {job_type}")
        self._handlers[job_type] = handler

    def get(self, job_type: str) -> JobHandler:
        try:
            return self._handlers[job_type]
        except KeyError as exc:
            raise KeyError(f"unknown job type: {job_type}") from exc
