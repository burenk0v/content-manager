import logging
import time
import uuid

from fastapi import Request

logger = logging.getLogger("content_manager.http")


async def request_observability(request: Request, call_next):
    request_id = request.headers.get("X-Request-ID") or uuid.uuid4().hex
    started = time.perf_counter()
    response = None
    try:
        response = await call_next(request)
        return response
    finally:
        duration_ms = round((time.perf_counter() - started) * 1000, 2)
        status_code = response.status_code if response is not None else 500
        logger.info(
            "http_request method=%s path=%s status=%s duration_ms=%s request_id=%s",
            request.method,
            request.url.path,
            status_code,
            duration_ms,
            request_id,
        )
        if response is not None:
            response.headers["X-Request-ID"] = request_id


def publication_event(
    event: str,
    publication_id: int,
    *,
    status: str | None = None,
    worker_id: str | None = None,
    attempt_count: int | None = None,
    error: str | None = None,
) -> None:
    logger.info(
        "publication_event event=%s publication_id=%s status=%s worker_id=%s attempt_count=%s error=%s",
        event,
        publication_id,
        status,
        worker_id,
        attempt_count,
        error,
    )
