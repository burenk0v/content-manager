import pytest
from fastapi.testclient import TestClient

from src.app import db
from src.app.main import app
from src.app.metrics import HTTP_REQUESTS
from src.app.routers.auth import get_secret_key


client = TestClient(app)


def _counter_value(method: str, path: str, status: str) -> float:
    for metric in HTTP_REQUESTS.collect():
        for sample in metric.samples:
            if sample.name.endswith("_total") and sample.labels == {
                "method": method,
                "path": path,
                "status": status,
            }:
                return sample.value
    return 0.0


def test_liveness_does_not_touch_database(monkeypatch):
    def fail_check():
        raise AssertionError("liveness must not depend on database")

    monkeypatch.setattr(db, "check_db_connection", fail_check)
    response = client.get("/health/live")
    assert response.status_code == 200
    assert response.json() == {"status": "ok"}


def test_readiness_returns_503_when_database_is_unavailable(monkeypatch):
    monkeypatch.setattr(db, "check_db_connection", lambda: False)
    response = client.get("/health/ready")
    assert response.status_code == 503
    assert response.json() == {"detail": "Database unavailable"}


def test_request_id_is_returned_and_request_metric_is_recorded():
    request_id = "phase4-test-request"
    before = _counter_value("GET", "/health/live", "200")
    response = client.get("/health/live", headers={"X-Request-ID": request_id})
    after = _counter_value("GET", "/health/live", "200")
    assert response.status_code == 200
    assert response.headers["X-Request-ID"] == request_id
    assert after == before + 1


def test_metrics_endpoint_exposes_prometheus_format():
    response = client.get("/metrics")
    assert response.status_code == 200
    assert "content_manager_http_requests_total" in response.text


def test_service_token_is_required_for_audit_endpoint(monkeypatch):
    monkeypatch.setenv("SERVICE_ACCOUNT_TOKEN", "phase4-secret")
    response = client.get("/audit")
    assert response.status_code == 401
    response = client.get("/audit", headers={"X-Service-Token": "phase4-secret"})
    assert response.status_code == 200


def test_auth_secret_is_required_in_production(monkeypatch):
    monkeypatch.delenv("BACKEND_SECRET_KEY", raising=False)
    monkeypatch.setenv("APP_ENV", "production")
    with pytest.raises(RuntimeError, match="BACKEND_SECRET_KEY"):
        get_secret_key()


def test_auth_secret_is_generated_in_development(monkeypatch):
    monkeypatch.delenv("BACKEND_SECRET_KEY", raising=False)
    monkeypatch.setenv("APP_ENV", "development")
    first = get_secret_key()
    second = get_secret_key()
    assert first
    assert second
    assert first != second
