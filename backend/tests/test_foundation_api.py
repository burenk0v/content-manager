import os

os.environ["SERVICE_ACCOUNT_TOKEN"] = "test-token"

from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from src.app.db import Base, get_db
from src.app.main import app

engine = create_engine("sqlite:///:memory:", connect_args={"check_same_thread": False})
TestingSession = sessionmaker(bind=engine, autocommit=False, autoflush=False)
Base.metadata.create_all(bind=engine)


def override_db():
    db = TestingSession()
    try:
        yield db
    finally:
        db.close()


app.dependency_overrides[get_db] = override_db
client = TestClient(app)
HEADERS = {"X-Service-Token": "test-token"}


def test_content_lifecycle_and_idempotent_publication():
    workspace = client.post("/content/workspaces", json={"name": "Test", "slug": "test"}, headers=HEADERS)
    assert workspace.status_code == 201
    workspace_id = workspace.json()["id"]

    channel = client.post("/content/channels", json={
        "workspace_id": workspace_id,
        "platform": "telegram",
        "external_id": "@test_channel",
    }, headers=HEADERS)
    assert channel.status_code == 201
    channel_id = channel.json()["id"]

    content = client.post("/content/contents", json={
        "workspace_id": workspace_id,
        "body": "Hello Phase 1",
        "language": "en",
        "source": "human",
    }, headers=HEADERS)
    assert content.status_code == 201
    content_id = content.json()["id"]

    versions = client.get(f"/content/contents/{content_id}/versions", headers=HEADERS)
    assert versions.status_code == 200
    assert len(versions.json()) == 1
    assert versions.json()[0]["version"] == 1

    payload = {"content_id": content_id, "channel_id": channel_id, "idempotency_key": "publish-1"}
    first = client.post("/content/publications", json=payload, headers=HEADERS)
    second = client.post("/content/publications", json=payload, headers=HEADERS)
    assert first.status_code == 201
    assert second.status_code == 201
    assert first.json()["id"] == second.json()["id"]


def test_service_token_is_required():
    response = client.get("/content/workspaces")
    assert response.status_code == 401
