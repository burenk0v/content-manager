from tests.test_autonomous_generation import create_profile
from tests.test_foundation_api import HEADERS, client, TestingSession
from src.app.models import Content


def _create_review_content(profile):
    db = TestingSession()
    try:
        content = Content(
            workspace_id=profile["workspace_id"],
            profile_id=profile["id"],
            title="Python review topic",
            language="en",
            status="review",
        )
        db.add(content)
        db.commit()
        db.refresh(content)
        return content.id
    finally:
        db.close()


def test_reject_is_idempotent_and_persists_reason():
    profile = create_profile()
    content_id = _create_review_content(profile)

    first = client.post(
        f"/content/contents/{content_id}/reject",
        json={"reason": "Needs a clearer example"},
        headers=HEADERS,
    )
    assert first.status_code == 200
    assert first.json()["status"] == "draft"

    second = client.post(
        f"/content/contents/{content_id}/reject",
        json={"reason": "same callback delivered again"},
        headers=HEADERS,
    )
    assert second.status_code == 200
    assert second.json()["status"] == "draft"


def test_regenerate_is_idempotent_and_queues_profile():
    profile = create_profile()
    content_id = _create_review_content(profile)

    first = client.post(
        f"/content/contents/{content_id}/regenerate",
        json={"reason": "Try a different angle"},
        headers=HEADERS,
    )
    assert first.status_code == 200
    assert first.json()["status"] == "draft"

    second = client.post(
        f"/content/contents/{content_id}/regenerate",
        json={"reason": "same callback delivered again"},
        headers=HEADERS,
    )
    assert second.status_code == 200
    assert second.json()["status"] == "draft"

    profile_response = client.get(f"/content/profiles/{profile['id']}", headers=HEADERS)
    assert profile_response.status_code == 200
    assert profile_response.json()["regeneration_requested"] is True


def test_notification_completion_requires_matching_claim_token():
    from datetime import datetime, timedelta
    from src.app.models import Content

    profile = create_profile()
    content_id = _create_review_content(profile)

    db = TestingSession()
    try:
        content = db.query(Content).filter(Content.id == content_id).one()
        content.approval_notification_claimed_at = datetime.utcnow()
        content.approval_notification_claim_token = "owner-token"
        db.commit()
    finally:
        db.close()

    stale = client.post(
        f"/content/contents/{content_id}/notification-complete",
        json={"claim_token": "stale-token"},
        headers=HEADERS,
    )
    assert stale.status_code == 409

    success = client.post(
        f"/content/contents/{content_id}/notification-complete",
        json={"claim_token": "owner-token"},
        headers=HEADERS,
    )
    assert success.status_code == 200
    assert success.json()["approval_notification_sent_at"] is not None
