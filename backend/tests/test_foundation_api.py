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
    workspace = client.post("/content/workspaces", json={"name": f"Test {suffix}", "slug": f"test-{suffix}"}, headers=HEADERS)
    assert workspace.status_code == 201
    workspace_id = workspace.json()["id"]
    channel = client.post("/content/channels", json={"workspace_id": workspace_id, "platform": "telegram", "external_id": f"@test_channel_{suffix}"}, headers=HEADERS)
    assert channel.status_code == 201
    channel_id = channel.json()["id"]
    content = client.post("/content/contents", json={"workspace_id": workspace_id, "body": "Hello Phase 1", "language": "en", "source": "human"}, headers=HEADERS)
    assert content.status_code == 201
    content_id = content.json()["id"]
    for target in ("review", "approved"):
        response = client.post(f"/content/contents/{content_id}/transition", json={"status": target}, headers=HEADERS)
        assert response.status_code == 200
    payload = {"content_id": content_id, "channel_id": channel_id, "idempotency_key": f"publish-{suffix}"}
    if scheduled_at is not None:
        payload["scheduled_at"] = scheduled_at
    publication = client.post("/content/publications", json=payload, headers=HEADERS)
    assert publication.status_code == 201
    return publication.json()


def test_publication_requires_approved_content():
    suffix = uuid.uuid4().hex[:8]
    workspace = client.post("/content/workspaces", json={"name": f"Gate {suffix}", "slug": f"gate-{suffix}"}, headers=HEADERS).json()
    channel = client.post("/content/channels", json={"workspace_id": workspace["id"], "platform": "telegram", "external_id": f"@gate_{suffix}"}, headers=HEADERS).json()
    content = client.post("/content/contents", json={"workspace_id": workspace["id"], "body": "Needs approval", "language": "en"}, headers=HEADERS).json()
    response = client.post("/content/publications", json={"content_id": content["id"], "channel_id": channel["id"]}, headers=HEADERS)
    assert response.status_code == 409


def test_content_lifecycle_and_idempotent_publication():
    publication = create_publication()
    second = client.post("/content/publications", json={"content_id": publication["content_id"], "channel_id": publication["channel_id"], "idempotency_key": publication["idempotency_key"]}, headers=HEADERS)
    assert second.status_code == 201
    assert second.json()["id"] == publication["id"]


def test_duplicate_content_channel_is_rejected_even_with_new_idempotency_key():
    publication = create_publication()
    response = client.post("/content/publications", json={"content_id": publication["content_id"], "channel_id": publication["channel_id"], "idempotency_key": f"different-{uuid.uuid4().hex}"}, headers=HEADERS)
    assert response.status_code == 409
    assert response.json()["detail"] == "Publication already exists for this content and channel"


def test_scheduled_content_can_add_second_channel():
    publication = create_publication()
    content_id = publication["content_id"]
    workspace_id = client.get("/content/contents", headers=HEADERS).json()[-1]["workspace_id"]
    suffix = uuid.uuid4().hex[:8]
    channel = client.post("/content/channels", json={"workspace_id": workspace_id, "platform": "telegram", "external_id": f"@second_{suffix}"}, headers=HEADERS)
    assert channel.status_code == 201
    second = client.post("/content/publications", json={"content_id": content_id, "channel_id": channel.json()["id"], "idempotency_key": f"second-{suffix}"}, headers=HEADERS)
    assert second.status_code == 201
    assert second.json()["content_id"] == content_id
    assert second.json()["channel_id"] == channel.json()["id"]
    assert client.get(f"/content/contents/{content_id}/transitions", headers=HEADERS).json()["status"] == "scheduled"


def test_multi_channel_content_publishes_only_after_all_channels_complete():
    first = create_publication(); content_id = first["content_id"]
    workspace_id = client.get("/content/contents", headers=HEADERS).json()[-1]["workspace_id"]
    suffix = uuid.uuid4().hex[:8]
    second_channel = client.post("/content/channels", json={"workspace_id": workspace_id, "platform": "telegram", "external_id": f"@multi_{suffix}"}, headers=HEADERS).json()
    second = client.post("/content/publications", json={"content_id": content_id, "channel_id": second_channel["id"], "idempotency_key": f"multi-{suffix}"}, headers=HEADERS).json()

    first_claim = client.post(f"/content/publications/{first['id']}/claim", json={"worker_id": "worker-a"}, headers=HEADERS)
    assert first_claim.status_code == 200
    first_token = first_claim.json()["processing_token"]
    assert client.post(f"/content/publications/{first['id']}/complete", json={"worker_id": "worker-a", "processing_token": first_token, "external_id": "tg-a"}, headers=HEADERS).status_code == 200
    assert client.get(f"/content/contents/{content_id}/transitions", headers=HEADERS).json()["status"] == "scheduled"

    second_claim = client.post(f"/content/publications/{second['id']}/claim", json={"worker_id": "worker-b"}, headers=HEADERS)
    assert second_claim.status_code == 200
    second_token = second_claim.json()["processing_token"]
    assert client.get(f"/content/contents/{content_id}/transitions", headers=HEADERS).json()["status"] == "publishing"
    completed = client.post(f"/content/publications/{second['id']}/complete", json={"worker_id": "worker-b", "processing_token": second_token, "external_id": "tg-b"}, headers=HEADERS)
    assert completed.status_code == 200
    assert client.get(f"/content/contents/{content_id}/transitions", headers=HEADERS).json()["status"] == "published"


def test_publication_rejects_cross_workspace_channel():
    first = create_publication(); suffix = uuid.uuid4().hex[:8]
    other_workspace = client.post("/content/workspaces", json={"name": f"Other {suffix}", "slug": f"other-{suffix}"}, headers=HEADERS).json()
    other_channel = client.post("/content/channels", json={"workspace_id": other_workspace["id"], "platform": "telegram", "external_id": f"@other_{suffix}"}, headers=HEADERS).json()
    response = client.post("/content/publications", json={"content_id": first["content_id"], "channel_id": other_channel["id"], "idempotency_key": f"cross-{suffix}"}, headers=HEADERS)
    assert response.status_code == 400


def test_published_content_cannot_add_publication():
    publication = create_publication()
    claim = client.post(f"/content/publications/{publication['id']}/claim", json={"worker_id": "worker-a"}, headers=HEADERS)
    token = claim.json()["processing_token"]
    assert client.post(f"/content/publications/{publication['id']}/complete", json={"worker_id": "worker-a", "processing_token": token, "external_id": "tg-1"}, headers=HEADERS).status_code == 200
    suffix = uuid.uuid4().hex[:8]
    workspace_id = client.get("/content/contents", headers=HEADERS).json()[-1]["workspace_id"]
    channel = client.post("/content/channels", json={"workspace_id": workspace_id, "platform": "telegram", "external_id": f"@late_{suffix}"}, headers=HEADERS).json()
    response = client.post("/content/publications", json={"content_id": publication["content_id"], "channel_id": channel["id"], "idempotency_key": f"late-{suffix}"}, headers=HEADERS)
    assert response.status_code == 409


def test_publication_ready_respects_schedule_and_active_channel():
    future = (datetime.utcnow() + timedelta(minutes=30)).isoformat()
    publication = create_publication(scheduled_at=future)
    ready = client.get("/content/publications/ready", headers=HEADERS)
    assert ready.status_code == 200
    assert publication["id"] not in {item["id"] for item in ready.json()}


def test_publication_claim_is_single_owner_and_can_complete():
    publication = create_publication(); publication_id = publication["id"]
    first = client.post(f"/content/publications/{publication_id}/claim", json={"worker_id": "worker-a"}, headers=HEADERS)
    assert first.status_code == 200
    assert first.json()["status"] == "processing" and first.json()["attempt_count"] == 1
    token = first.json()["processing_token"]
    assert token
    assert client.get(f"/content/contents/{publication['content_id']}/transitions", headers=HEADERS).json()["status"] == "publishing"
    second = client.post(f"/content/publications/{publication_id}/claim", json={"worker_id": "worker-b"}, headers=HEADERS)
    assert second.status_code == 409
    wrong_worker = client.post(f"/content/publications/{publication_id}/complete", json={"worker_id": "worker-b", "processing_token": token, "external_id": "tg-1"}, headers=HEADERS)
    assert wrong_worker.status_code == 409
    completed = client.post(f"/content/publications/{publication_id}/complete", json={"worker_id": "worker-a", "processing_token": token, "external_id": "tg-1"}, headers=HEADERS)
    assert completed.status_code == 200
    assert completed.json()["status"] == "published"
    assert client.get(f"/content/contents/{publication['content_id']}/transitions", headers=HEADERS).json()["status"] == "published"


def test_old_processing_token_cannot_complete_after_stale_recovery():
    publication_id = create_publication()["id"]
    claimed = client.post(f"/content/publications/{publication_id}/claim", json={"worker_id": "dead-worker"}, headers=HEADERS)
    assert claimed.status_code == 200
    old_token = claimed.json()["processing_token"]
    db = TestingSession()
    try:
        publication = db.query(Publication).filter(Publication.id == publication_id).one()
        publication.processing_started_at = datetime.utcnow() - timedelta(hours=1)
        db.commit()
    finally:
        db.close()

    recovered = client.post("/content/publications/recover-stale?stale_after_seconds=60", headers=HEADERS)
    assert recovered.status_code == 200
    item = next(item for item in recovered.json() if item["id"] == publication_id)
    assert item["status"] == "scheduled" and item["processing_token"] is None

    stale_complete = client.post(f"/content/publications/{publication_id}/complete", json={"worker_id": "dead-worker", "processing_token": old_token, "external_id": "late"}, headers=HEADERS)
    assert stale_complete.status_code == 409

    re_claimed = client.post(f"/content/publications/{publication_id}/claim", json={"worker_id": "new-worker"}, headers=HEADERS)
    assert re_claimed.status_code == 200
    assert re_claimed.json()["processing_token"] != old_token


def test_publication_failure_can_be_retried_then_failed():
    publication = create_publication(); publication_id = publication["id"]
    claimed = client.post(f"/content/publications/{publication_id}/claim", json={"worker_id": "worker-a"}, headers=HEADERS)
    assert claimed.status_code == 200
    token = claimed.json()["processing_token"]
    retried = client.post(f"/content/publications/{publication_id}/fail", json={"worker_id": "worker-a", "processing_token": token, "error_message": "temporary", "retry_delay_seconds": 1}, headers=HEADERS)
    assert retried.status_code == 200 and retried.json()["status"] == "scheduled"
    assert retried.json()["attempt_count"] == 1 and retried.json()["next_attempt_at"] is not None
    assert retried.json()["processing_token"] is None
    assert client.get(f"/content/contents/{publication['content_id']}/transitions", headers=HEADERS).json()["status"] == "scheduled"


def test_stale_processing_claim_can_be_recovered():
    publication_id = create_publication()["id"]
    claimed = client.post(f"/content/publications/{publication_id}/claim", json={"worker_id": "dead-worker"}, headers=HEADERS)
    assert claimed.status_code == 200
    db = TestingSession()
    try:
        publication = db.query(Publication).filter(Publication.id == publication_id).one()
        publication.processing_started_at = datetime.utcnow() - timedelta(hours=1)
        db.commit()
    finally:
        db.close()
    recovered = client.post("/content/publications/recover-stale?stale_after_seconds=60", headers=HEADERS)
    assert recovered.status_code == 200
    item = next(item for item in recovered.json() if item["id"] == publication_id)
    assert item["status"] == "scheduled" and item["worker_id"] is None and item["processing_started_at"] is None and item["processing_token"] is None
    assert client.get(f"/content/contents/{item['content_id']}/transitions", headers=HEADERS).json()["status"] == "scheduled"


def test_service_token_is_required():
    response = client.get("/content/workspaces")
    assert response.status_code == 401
