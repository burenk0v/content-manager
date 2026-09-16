import logging
import time
import uuid

from fastapi import Request

from src.app.audit import set_request_id
from src.app.metrics import HTTP_REQUESTS, HTTP_REQUEST_DURATION, PUBLICATION_EVENTS

logger = logging.getLogger("content_manager.http")


async def request_observability(request: Request, call_next):
    request_id = request.headers.get("X-Request-ID") or uuid.uuid4().hex
    set_request_id(request_id)
    started = time.perf_counter()
    response = None
    try:
        response = await call_next(request)
        return response
    finally:
        duration_seconds = time.perf_counter() - started
        duration_ms = round(duration_seconds * 1000, 2)
        status_code = response.status_code if response is not None else 500
        route = request.scope.get("route")
        path = getattr(route, "path", request.url.path)
        HTTP_REQUESTS.labels(request.method, path, str(status_code)).inc()
        HTTP_REQUEST_DURATION.labels(request.method, path).observe(duration_seconds)
        logger.info(
            "http_request method=%s path=%s status=%s duration_ms=%s request_id=%s",
            request.method,
            path,
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
    error: Exception | None = None,
) -> None:
    PUBLICATION_EVENTS.labels(event, status or "unknown").inc()
    logger.info(
        "publication_event event=%s publication_id=%s status=%s worker_id=%s attempt_count=%s error_type=%s",
        event,
        publication_id,
        status,
        worker_id,
        attempt_count,
        type(error).__name__ if error is not None else None,
    )
