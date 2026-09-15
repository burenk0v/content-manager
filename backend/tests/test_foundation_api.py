import os
import uuid
from datetime import datetime, timedelta

os.environ["SERVICE_ACCOUNT_TOKEN"] = "test-token"

from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from src.app.db import Base, get_db
from src.app.main import app
from src.app.models import Publication

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


def create_publication(scheduled_at=None):
    suffix = uuid.uuid4().hex[:8]
    workspace = client.post(
        "/content/workspaces",
        json={"name": f"Test {suffix}", "slug": f"test-{suffix}"},
        headers=HEADERS,
    )
    assert workspace.status_code == 201
    workspace_id = workspace.json()["id"]

    channel = client.post(
        "/content/channels",
        json={
            "workspace_id": workspace_id,
            "platform": "telegram",
            "external_id": f"@test_channel_{suffix}",
        },
        headers=HEADERS,
    )
    assert channel.status_code == 201
    channel_id = channel.json()["id"]

    content = client.post(
        "/content/contents",
        json={
            "workspace_id": workspace_id,
            "body": "Hello Phase 1",
            "language": "en",
            "source": "human",
        },
        headers=HEADERS,
    )
    assert content.status_code == 201
    content_id = content.json()["id"]

    payload = {
        "content_id": content_id,
        "channel_id": channel_id,
        "idempotency_key": f"publish-{suffix}",
    }
    if scheduled_at is not None:
        payload["scheduled_at"] = scheduled_at

    publication = client.post("/content/publications", json=payload, headers=HEADERS)
    assert publication.status_code == 201
    return publication.json()


def test_content_lifecycle_and_idempotent_publication():
    publication = create_publication()
    second = client.post(
        "/content/publications",
        json={
            "content_id": publication["content_id"],
            "channel_id": publication["channel_id"],
            "idempotency_key": publication["idempotency_key"],
        },
        headers=HEADERS,
    )
    assert second.status_code == 201
    assert second.json()["id"] == publication["id"]


def test_publication_ready_respects_schedule_and_active_channel():
    future = (datetime.utcnow() + timedelta(minutes=30)).isoformat()
    publication = create_publication(scheduled_at=future)

    ready = client.get("/content/publications/ready", headers=HEADERS)
    assert ready.status_code == 200
    assert publication["id"] not in {item["id"] for item in ready.json()}


def test_publication_claim_is_single_owner_and_can_complete():
    publication_id = create_publication()["id"]

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
    publication_id = create_publication()["id"]

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


def test_stale_processing_claim_can_be_recovered():
    publication_id = create_publication()["id"]
    claimed = client.post(
        f"/content/publications/{publication_id}/claim",
        json={"worker_id": "dead-worker"},
        headers=HEADERS,
    )
    assert claimed.status_code == 200

    db = TestingSession()
    try:
        publication = db.query(Publication).filter(Publication.id == publication_id).one()
        publication.processing_started_at = datetime.utcnow() - timedelta(hours=1)
        db.commit()
    finally:
        db.close()

    recovered = client.post(
        "/content/publications/recover-stale?stale_after_seconds=60",
        headers=HEADERS,
    )
    assert recovered.status_code == 200
    item = next(item for item in recovered.json() if item["id"] == publication_id)
    assert item["status"] == "scheduled"
    assert item["worker_id"] is None
    assert item["processing_started_at"] is None


def test_service_token_is_required():
    response = client.get("/content/workspaces")
    assert response.status_code == 401
