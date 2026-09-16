from prometheus_client import CONTENT_TYPE_LATEST, Counter, Histogram, generate_latest


HTTP_REQUESTS = Counter(
    "content_manager_http_requests_total",
    "Total HTTP requests handled by the backend.",
    ("method", "path", "status"),
)
HTTP_REQUEST_DURATION = Histogram(
    "content_manager_http_request_duration_seconds",
    "HTTP request duration in seconds.",
    ("method", "path"),
)
PUBLICATION_EVENTS = Counter(
    "content_manager_publication_events_total",
    "Publication lifecycle events.",
    ("event", "status"),
)


def metrics_response() -> tuple[bytes, str]:
    return generate_latest(), CONTENT_TYPE_LATEST
