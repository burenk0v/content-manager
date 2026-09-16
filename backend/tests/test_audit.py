import os
import tempfile
import uuid

os.environ["SERVICE_ACCOUNT_TOKEN"] = "test-token"

from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import NullPool

from src.app.db import Base, get_db
from src.app.main import app
from src.app.models import AuditLog

_fd, _db_path = tempfile.mkstemp(prefix="content_manager_audit_test_", suffix=".sqlite3")
os.close(_fd)
engine = create_engine(
    f"sqlite:///{_db_path}",
    connect_args={"check_same_thread": False, "timeout": 30},
    poolclass=NullPool,
)
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


def test_audit_endpoint_exposes_structured_metadata_and_request_id():
    suffix = uuid.uuid4().hex[:8]
    request_id = f"audit-{suffix}"
    response = client.post(
        "/content/workspaces",
        json={"name": f"Audit {suffix}", "slug": f"audit-{suffix}"},
        headers={**HEADERS, "X-Request-ID": request_id},
    )
    assert response.status_code == 201
    assert response.headers["X-Request-ID"] == request_id

    events = client.get(
        "/audit",
        params={"request_id": request_id, "event_type": "workspace.created"},
        headers=HEADERS,
    )
    assert events.status_code == 200
    payload = events.json()
    assert len(payload) == 1
    assert payload[0]["request_id"] == request_id
    assert payload[0]["event_type"] == "workspace.created"
    assert payload[0]["entity_type"] == "workspace"
    assert payload[0]["action"] == "created"
    assert payload[0]["metadata"] is None


def test_content_lifecycle_audit_records_state_transition():
    suffix = uuid.uuid4().hex[:8]
    workspace = client.post(
        "/content/workspaces",
        json={"name": f"Lifecycle {suffix}", "slug": f"lifecycle-{suffix}"},
        headers=HEADERS,
    ).json()
    content = client.post(
        "/content/contents",
        json={
            "workspace_id": workspace["id"],
            "body": "Audit me",
            "language": "en",
            "source": "human",
        },
        headers=HEADERS,
    ).json()
    request_id = f"transition-{suffix}"
    transition = client.post(
        f"/content/contents/{content['id']}/transition",
        json={"status": "review"},
        headers={**HEADERS, "X-Request-ID": request_id},
    )
    assert transition.status_code == 200

    events = client.get(
        "/audit",
        params={
            "entity_type": "content",
            "entity_id": content["id"],
            "event_type": "content.status_changed",
            "request_id": request_id,
        },
        headers=HEADERS,
    )
    assert events.status_code == 200
    payload = events.json()
    assert len(payload) == 1
    assert payload[0]["metadata"] == {"from": "draft", "to": "review"}
    assert payload[0]["request_id"] == request_id


def test_publication_audit_contains_attempt_and_provider_outcome_events():
    suffix = uuid.uuid4().hex[:8]
    workspace = client.post(
        "/content/workspaces",
        json={"name": f"Publication {suffix}", "slug": f"publication-{suffix}"},
        headers=HEADERS,
    ).json()
    channel = client.post(
        "/content/channels",
        json={"workspace_id": workspace["id"], "platform": "telegram", "external_id": f"@audit_{suffix}"},
        headers=HEADERS,
    ).json()
    content = client.post(
        "/content/contents",
        json={"workspace_id": workspace["id"], "body": "Publish audit", "language": "en"},
        headers=HEADERS,
    ).json()
    for target in ("review", "approved"):
        assert client.post(
            f"/content/contents/{content['id']}/transition",
            json={"status": target},
            headers=HEADERS,
        ).status_code == 200

    publication = client.post(
        "/content/publications",
        json={"content_id": content["id"], "channel_id": channel["id"], "idempotency_key": f"audit-pub-{suffix}"},
        headers=HEADERS,
    ).json()
    claimed = client.post(
        f"/content/publications/{publication['id']}/claim",
        json={"worker_id": "audit-worker"},
        headers=HEADERS,
    ).json()
    token = claimed["processing_token"]
    completed = client.post(
        f"/content/publications/{publication['id']}/complete",
        json={"worker_id": "audit-worker", "processing_token": token, "external_id": "tg-audit"},
        headers=HEADERS,
    )
    assert completed.status_code == 200

    db = TestingSession()
    try:
        events = (
            db.query(AuditLog)
            .filter(AuditLog.entity_type == "publication", AuditLog.entity_id == publication["id"])
            .order_by(AuditLog.id.asc())
            .all()
        )
        assert [event.event_type for event in events] == [
            "publication.scheduled",
            "publication.claimed",
            "publication.published",
        ]
        assert events[1].metadata_json == {"worker_id": "audit-worker", "attempt_count": 1}
        assert events[2].metadata_json["external_id"] == "tg-audit"
    finally:
        db.close()
