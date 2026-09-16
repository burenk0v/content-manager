from backend.tests.test_foundation_api import HEADERS, TestingSession, client, create_publication
from src.app.models import PublicationOperation


def test_publication_creates_distinct_provider_operation_identity():
    publication = create_publication()
    assert publication["idempotency_key"] != publication["provider_operation_key"]
    assert publication["provider_operation_status"] == "pending"
    assert publication["provider_operation_attempt_count"] == 0

    db = TestingSession()
    try:
        operation = db.query(PublicationOperation).filter(PublicationOperation.publication_id == publication["id"]).one()
        assert operation.provider == "telegram"
        assert operation.operation_key == publication["provider_operation_key"]
        assert operation.status == "pending"
        assert operation.attempt_count == 0
    finally:
        db.close()


def test_provider_operation_key_is_reused_across_retry_attempts():
    publication = create_publication()
    operation_key = publication["provider_operation_key"]

    first = client.post(
        f"/content/publications/{publication['id']}/claim",
        json={"worker_id": "worker-a"},
        headers=HEADERS,
    )
    assert first.status_code == 200
    assert first.json()["provider_operation_key"] == operation_key
    assert first.json()["provider_operation_attempt_count"] == 1
    token = first.json()["processing_token"]

    failed = client.post(
        f"/content/publications/{publication['id']}/fail",
        json={
            "worker_id": "worker-a",
            "processing_token": token,
            "error_message": "temporary provider failure",
            "retry": True,
        },
        headers=HEADERS,
    )
    assert failed.status_code == 200
    assert failed.json()["provider_operation_key"] == operation_key
    assert failed.json()["provider_operation_status"] == "failed"

    db = TestingSession()
    try:
        operation = db.query(PublicationOperation).filter(PublicationOperation.publication_id == publication["id"]).one()
        assert operation.operation_key == operation_key
        assert operation.attempt_count == 1
        assert operation.status == "failed"
    finally:
        db.close()


def test_ambiguous_provider_outcome_is_terminal_until_reconciliation():
    publication = create_publication()
    claimed = client.post(
        f"/content/publications/{publication['id']}/claim",
        json={"worker_id": "worker-a"},
        headers=HEADERS,
    )
    assert claimed.status_code == 200
    token = claimed.json()["processing_token"]

    failed = client.post(
        f"/content/publications/{publication['id']}/fail",
        json={
            "worker_id": "worker-a",
            "processing_token": token,
            "error_message": "provider outcome unknown",
            "retry": False,
        },
        headers=HEADERS,
    )
    assert failed.status_code == 200
    assert failed.json()["status"] == "failed"
    assert failed.json()["provider_operation_status"] == "unknown"
    assert failed.json()["next_attempt_at"] is None

    db = TestingSession()
    try:
        operation = db.query(PublicationOperation).filter(PublicationOperation.publication_id == publication["id"]).one()
        assert operation.status == "unknown"
        assert operation.last_error == "provider outcome unknown"
    finally:
        db.close()
