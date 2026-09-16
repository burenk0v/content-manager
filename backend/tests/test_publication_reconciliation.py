from datetime import datetime, timedelta

from src.app.models import Publication, PublicationOperation
from tests.test_foundation_api import HEADERS, TestingSession, client


def _create_publication(slug: str) -> int:
    workspace = client.post("/content/workspaces", json={"name": slug, "slug": slug.lower()}, headers=HEADERS)
    assert workspace.status_code == 201
    workspace_id = workspace.json()["id"]
    channel = client.post("/content/channels", json={"workspace_id": workspace_id, "platform": "telegram", "external_id": f"@{slug.lower()}", "timezone": "UTC"}, headers=HEADERS)
    assert channel.status_code == 201
    content = client.post("/content/contents", json={"workspace_id": workspace_id, "body": "hello", "language": "en"}, headers=HEADERS)
    assert content.status_code == 201
    content_id = content.json()["id"]
    assert client.post(f"/content/contents/{content_id}/transition", json={"status": "review"}, headers=HEADERS).status_code == 200
    assert client.post(f"/content/contents/{content_id}/transition", json={"status": "approved"}, headers=HEADERS).status_code == 200
    publication = client.post("/content/publications", json={"content_id": content_id, "channel_id": channel.json()["id"]}, headers=HEADERS)
    assert publication.status_code == 201
    return publication.json()["id"]


def _make_provider_outcome_unknown(publication_id: int) -> str:
    claimed = client.post(f"/content/publications/{publication_id}/claim", json={"worker_id": "worker"}, headers=HEADERS)
    assert claimed.status_code == 200
    db = TestingSession()
    try:
        item = db.query(Publication).filter(Publication.id == publication_id).one()
        item.lease_heartbeat_at = datetime.utcnow() - timedelta(hours=1)
        db.commit()
    finally:
        db.close()
    recovered = client.post("/content/publications/recover-stale", headers=HEADERS)
    assert recovered.status_code == 200
    item = next(item for item in recovered.json() if item["id"] == publication_id)
    assert item["provider_operation_status"] == "unknown"
    return item["provider_operation_key"]


def test_unknown_provider_outcome_can_be_reconciled_as_published():
    publication_id = _create_publication("recon")
    operation_key = _make_provider_outcome_unknown(publication_id)
    resolved = client.post(f"/content/publications/{publication_id}/reconcile", json={"outcome": "published", "external_id": "telegram:123"}, headers=HEADERS)
    assert resolved.status_code == 200
    assert resolved.json()["status"] == "published"
    assert resolved.json()["external_id"] == "telegram:123"
    assert resolved.json()["provider_operation_status"] == "succeeded"
    assert resolved.json()["provider_operation_key"] == operation_key
    db = TestingSession()
    try:
        operation = db.query(PublicationOperation).filter(PublicationOperation.publication_id == publication_id).one()
        assert operation.status == "succeeded"
        assert operation.external_id == "telegram:123"
    finally:
        db.close()


def test_unknown_provider_outcome_can_be_reconciled_as_retry():
    publication_id = _create_publication("recon-retry")
    operation_key = _make_provider_outcome_unknown(publication_id)
    resolved = client.post(f"/content/publications/{publication_id}/reconcile", json={"outcome": "retry", "error_message": "provider confirmed no delivery"}, headers=HEADERS)
    assert resolved.status_code == 200
    assert resolved.json()["status"] == "scheduled"
    assert resolved.json()["provider_operation_status"] == "pending"
    assert resolved.json()["next_attempt_at"] is not None
    assert resolved.json()["provider_operation_key"] == operation_key
    claimed_again = client.post(f"/content/publications/{publication_id}/claim", json={"worker_id": "worker-2"}, headers=HEADERS)
    assert claimed_again.status_code == 200
    assert claimed_again.json()["provider_operation_key"] == operation_key


def test_reconciliation_requires_unknown_provider_operation():
    publication_id = _create_publication("recon-guard")
    response = client.post(f"/content/publications/{publication_id}/reconcile", json={"outcome": "published", "external_id": "telegram:999"}, headers=HEADERS)
    assert response.status_code == 409
