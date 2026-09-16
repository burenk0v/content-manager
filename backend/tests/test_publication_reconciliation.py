from datetime import datetime, timedelta

from src.app.models import Publication, PublicationOperation

from .conftest import HEADERS, TestingSession, client


def test_unknown_provider_outcome_can_be_reconciled_as_published():
    response = client.post("/content/workspaces", json={"name": "Recon", "slug": "recon"}, headers=HEADERS)
    assert response.status_code == 201
    workspace_id = response.json()["id"]
    channel = client.post(
        "/content/channels",
        json={"workspace_id": workspace_id, "platform": "telegram", "external_id": "@recon", "timezone": "UTC"},
        headers=HEADERS,
    )
    assert channel.status_code == 201
    channel_id = channel.json()["id"]
    content = client.post(
        "/content/contents",
        json={"workspace_id": workspace_id, "body": "hello", "language": "en"},
        headers=HEADERS,
    )
    assert content.status_code == 201
    content_id = content.json()["id"]
    assert client.post(f"/content/contents/{content_id}/transition", json={"target": "review"}, headers=HEADERS).status_code == 200
    assert client.post(f"/content/contents/{content_id}/transition", json={"target": "approved"}, headers=HEADERS).status_code == 200
    publication = client.post(
        "/content/publications",
        json={"content_id": content_id, "channel_id": channel_id},
        headers=HEADERS,
    ).json()
    publication_id = publication["id"]
    claimed = client.post(f"/content/publications/{publication_id}/claim", json={"worker_id": "worker"}, headers=HEADERS)
    assert claimed.status_code == 200
    token = claimed.json()["processing_token"]

    db = TestingSession()
    try:
        item = db.query(Publication).filter(Publication.id == publication_id).one()
        item.lease_heartbeat_at = datetime.utcnow() - timedelta(hours=1)
        db.commit()
    finally:
        db.close()

    recovered = client.post("/content/publications/recover-stale", headers=HEADERS)
    assert recovered.status_code == 200
    assert next(item for item in recovered.json() if item["id"] == publication_id)["provider_operation_status"] == "unknown"

    resolved = client.post(
        f"/content/publications/{publication_id}/reconcile",
        json={"outcome": "published", "external_id": "telegram:123"},
        headers=HEADERS,
    )
    assert resolved.status_code == 200
    assert resolved.json()["status"] == "published"
    assert resolved.json()["external_id"] == "telegram:123"
    assert resolved.json()["provider_operation_status"] == "succeeded"

    db = TestingSession()
    try:
        operation = db.query(PublicationOperation).filter(PublicationOperation.publication_id == publication_id).one()
        assert operation.status == "succeeded"
        assert operation.external_id == "telegram:123"
    finally:
        db.close()


def test_unknown_provider_outcome_can_be_reconciled_as_retry():
    response = client.post("/content/workspaces", json={"name": "Recon Retry", "slug": "recon-retry"}, headers=HEADERS)
    workspace_id = response.json()["id"]
    channel_id = client.post(
        "/content/channels",
        json={"workspace_id": workspace_id, "platform": "telegram", "external_id": "@recon-retry", "timezone": "UTC"},
        headers=HEADERS,
    ).json()["id"]
    content_id = client.post(
        "/content/contents",
        json={"workspace_id": workspace_id, "body": "hello", "language": "en"},
        headers=HEADERS,
    ).json()["id"]
    assert client.post(f"/content/contents/{content_id}/transition", json={"target": "review"}, headers=HEADERS).status_code == 200
    assert client.post(f"/content/contents/{content_id}/transition", json={"target": "approved"}, headers=HEADERS).status_code == 200
    publication_id = client.post(
        "/content/publications",
        json={"content_id": content_id, "channel_id": channel_id},
        headers=HEADERS,
    ).json()["id"]
    claimed = client.post(f"/content/publications/{publication_id}/claim", json={"worker_id": "worker"}, headers=HEADERS)
    assert claimed.status_code == 200

    db = TestingSession()
    try:
        item = db.query(Publication).filter(Publication.id == publication_id).one()
        item.lease_heartbeat_at = datetime.utcnow() - timedelta(hours=1)
        db.commit()
    finally:
        db.close()
    assert client.post("/content/publications/recover-stale", headers=HEADERS).status_code == 200

    resolved = client.post(
        f"/content/publications/{publication_id}/reconcile",
        json={"outcome": "retry", "error_message": "provider confirmed no delivery"},
        headers=HEADERS,
    )
    assert resolved.status_code == 200
    assert resolved.json()["status"] == "scheduled"
    assert resolved.json()["provider_operation_status"] == "pending"
    assert resolved.json()["next_attempt_at"] is not None

    claimed_again = client.post(f"/content/publications/{publication_id}/claim", json={"worker_id": "worker-2"}, headers=HEADERS)
    assert claimed_again.status_code == 200
    assert claimed_again.json()["provider_operation_key"] == resolved.json()["provider_operation_key"]


def test_reconciliation_requires_unknown_provider_operation():
    response = client.post("/content/workspaces", json={"name": "Recon Guard", "slug": "recon-guard"}, headers=HEADERS)
    workspace_id = response.json()["id"]
    channel_id = client.post(
        "/content/channels",
        json={"workspace_id": workspace_id, "platform": "telegram", "external_id": "@recon-guard", "timezone": "UTC"},
        headers=HEADERS,
    ).json()["id"]
    content_id = client.post(
        "/content/contents",
        json={"workspace_id": workspace_id, "body": "hello", "language": "en"},
        headers=HEADERS,
    ).json()["id"]
    assert client.post(f"/content/contents/{content_id}/transition", json={"target": "review"}, headers=HEADERS).status_code == 200
    assert client.post(f"/content/contents/{content_id}/transition", json={"target": "approved"}, headers=HEADERS).status_code == 200
    publication_id = client.post(
        "/content/publications",
        json={"content_id": content_id, "channel_id": channel_id},
        headers=HEADERS,
    ).json()["id"]
    response = client.post(
        f"/content/publications/{publication_id}/reconcile",
        json={"outcome": "published", "external_id": "telegram:999"},
        headers=HEADERS,
    )
    assert response.status_code == 409
