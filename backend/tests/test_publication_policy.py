from datetime import datetime, timedelta

from src.app.domain.publication_policy import can_publish_content


def test_approved_content_is_publishable_when_due() -> None:
    now = datetime(2026, 9, 16, 12, 0, 0)
    decision = can_publish_content("approved", now - timedelta(minutes=1), now)
    assert decision.allowed is True


def test_unapproved_content_is_not_publishable() -> None:
    now = datetime(2026, 9, 16, 12, 0, 0)
    decision = can_publish_content("review", now, now)
    assert decision.allowed is False


def test_future_schedule_is_not_publishable() -> None:
    now = datetime(2026, 9, 16, 12, 0, 0)
    decision = can_publish_content("approved", now + timedelta(minutes=1), now)
    assert decision.allowed is False
