import uuid

from test_foundation_api import HEADERS, client


def test_content_api_rejects_missing_service_token():
    response = client.get("/content/workspaces")
    assert response.status_code == 401


def test_content_api_rejects_invalid_service_token():
    response = client.get("/content/workspaces", headers={"X-Service-Token": "wrong"})
    assert response.status_code == 401


def test_content_api_accepts_configured_service_token():
    suffix = uuid.uuid4().hex[:8]
    response = client.post("/content/workspaces", json={"name": f"Secure {suffix}", "slug": f"secure-{suffix}"}, headers=HEADERS)
    assert response.status_code == 201
