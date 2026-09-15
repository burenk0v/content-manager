import os

os.environ["SERVICE_ACCOUNT_TOKEN"] = "test-token"

from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from src.app.db import Base, get_db
from src.app.main import app

engine = create_engine("sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool)
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


def create_publication():
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

    publication = client.post("/content/publications", json={
        "content_id": content_id,
        "channel_id": channel_id,
        "idempotency_key": "publish-1",
    }, headers=HEADERS)
    assert publication.status_code == 201
    return publication.json()["id"]


def test_content_lifecycle_and_idempotent_publication():
    publication_id = create_publication()
    second = client.post("/content/publications", json={
        "content_id": 1,
        "channel_id": 1,
        "idempotency_key": "publish-1",
    }, headers=HEADERS)
    assert second.status_code == 201
    assert second.json()["id"] == publication_id


def test_publication_claim_is_single_owner_and_can_complete():
    publication_id = create_publication()

    first = client.post(
        f"/content/publications/{publication_id}/claim",
        json={"worker_id": "worker-a"},
        headers=HEADERS,
    )
    assert first.status_code == 200
    assert first.json()["status"] == "processing"
    assert first.json()["attempt_count"] == 1

    second = client.post(
        f"/content/publications/{publication_id}/claim",
        json={"worker_id": "worker-b"},
        headers=HEADERS,
    )
    assert second.status_code == 409

    wrong_worker = client.post(
        f"/content/publications/{publication_id}/complete",
        json={"worker_id": "worker-b", "external_id": "tg-1"},
        headers=HEADERS,
    )
    assert wrong_worker.status_code == 409

    completed = client.post(
        f"/content/publications/{publication_id}/complete",
        json={"worker_id": "worker-a", "external_id": "tg-1"},
        headers=HEADERS,
    )
    assert completed.status_code == 200
    assert completed.json()["status"] == "published"
    assert completed.json()["external_id"] == "tg-1"


def test_publication_failure_can_be_retried_then_failed():
    publication_id = create_publication()

    claimed = client.post(
        f"/content/publications/{publication_id}/claim",
        json={"worker_id": "worker-a"},
        headers=HEADERS,
    )
    assert claimed.status_code == 200

    retried = client.post(
        f"/content/publications/{publication_id}/fail",
        json={"worker_id": "worker-a", "error_message": "temporary", "retry_delay_seconds": 1},
        headers=HEADERS,
    )
    assert retried.status_code == 200
    assert retried.json()["status"] == "scheduled"
    assert retried.json()["attempt_count"] == 1
    assert retried.json()["next_attempt_at"] is not None

    claimed_again = client.post(
        f"/content/publications/{publication_id}/claim",
        json={"worker_id": "worker-b"},
        headers=HEADERS,
    )
    assert claimed_again.status_code == 409


def test_service_token_is_required():
    response = client.get("/content/workspaces")
    assert response.status_code == 401
