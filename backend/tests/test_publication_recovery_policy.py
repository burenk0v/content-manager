from datetime import datetime, timedelta

from src.app.models import Publication
from src.app.services.publication_service import retry_max_attempts
from tests.test_foundation_api import HEADERS, TestingSession, client, create_publication


def test_stale_provider_operation_requires_reconciliation():
    publication = create_publication()
    publication_id = publication["id"]
    claimed = client.post(
        f"/content/publications/{publication_id}/claim",
        json={"worker_id": "dead-worker"},
        headers=HEADERS,
    )
    assert claimed.status_code == 200

    db = TestingSession()
    try:
        item = db.query(Publication).filter(Publication.id == publication_id).one()
        stale_at = datetime.utcnow() - timedelta(hours=1)
        item.processing_started_at = stale_at
        item.lease_heartbeat_at = stale_at
        db.commit()
    finally:
        db.close()

    recovered = client.post("/content/publications/recover-stale", headers=HEADERS)
    assert recovered.status_code == 200
    item = next(row for row in recovered.json() if row["id"] == publication_id)
    assert item["status"] == "failed"
    assert item["processing_token"] is None
    assert item["lease_heartbeat_at"] is None

    stale_complete = client.post(
        f"/content/publications/{publication_id}/complete",
        json={
            "worker_id": "dead-worker",
            "processing_token": claimed.json()["processing_token"],
            "external_id": "late",
        },
        headers=HEADERS,
    )
    assert stale_complete.status_code == 409

    reconciled = client.post(
        f"/content/publications/{publication_id}/reconcile",
        json={"outcome": "retry"},
        headers=HEADERS,
    )
    assert reconciled.status_code == 200
    assert reconciled.json()["status"] == "scheduled"


def test_stale_provider_operation_can_be_reconciled_as_published():
    publication = create_publication()
    publication_id = publication["id"]
    claimed = client.post(
        f"/content/publications/{publication_id}/claim",
        json={"worker_id": "dead-worker"},
        headers=HEADERS,
    )
    assert claimed.status_code == 200

    db = TestingSession()
    try:
        item = db.query(Publication).filter(Publication.id == publication_id).one()
        stale_at = datetime.utcnow() - timedelta(hours=1)
        item.processing_started_at = stale_at
        item.lease_heartbeat_at = stale_at
        db.commit()
    finally:
        db.close()

    assert client.post("/content/publications/recover-stale", headers=HEADERS).status_code == 200
    reconciled = client.post(
        f"/content/publications/{publication_id}/reconcile",
        json={"outcome": "published", "external_id": "telegram:123"},
        headers=HEADERS,
    )
    assert reconciled.status_code == 200
    assert reconciled.json()["status"] == "published"
    assert client.get(
        f"/content/contents/{publication['content_id']}/transitions", headers=HEADERS
    ).json()["status"] == "published"


def test_retry_attempts_respect_backend_delay_and_maximum():
    publication = create_publication()
    publication_id = publication["id"]

    for expected_attempt in range(1, retry_max_attempts() + 1):
        if expected_attempt > 1:
            db = TestingSession()
            try:
                item = db.query(Publication).filter(Publication.id == publication_id).one()
                item.next_attempt_at = datetime.utcnow() - timedelta(seconds=1)
                db.commit()
            finally:
                db.close()

        claimed = client.post(
            f"/content/publications/{publication_id}/claim",
            json={"worker_id": f"worker-{expected_attempt}"},
            headers=HEADERS,
        )
        assert claimed.status_code == 200
        token = claimed.json()["processing_token"]
        failed = client.post(
            f"/content/publications/{publication_id}/fail",
            json={
                "worker_id": f"worker-{expected_attempt}",
                "processing_token": token,
                "error_message": "temporary",
                "retry": True,
            },
            headers=HEADERS,
        )
        assert failed.status_code == 200
        expected_status = "scheduled" if expected_attempt < retry_max_attempts() else "failed"
        assert failed.json()["status"] == expected_status
        assert failed.json()["attempt_count"] == expected_attempt
