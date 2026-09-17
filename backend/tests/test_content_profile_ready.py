from datetime import datetime, timezone

from src.app.models import ContentProfile
from src.app.services.content_profile_scheduler import is_profile_ready


def make_profile(**kwargs):
    values = {
        "name": "Daily",
        "schedule_type": "interval",
        "schedule_value": "60",
        "is_active": True,
    }
    values.update(kwargs)
    return ContentProfile(**values)


def test_inactive_profile_is_not_ready():
    profile = make_profile(is_active=False)
    assert is_profile_ready(profile, datetime.now(timezone.utc)) is False


def test_interval_profile_is_ready_without_previous_run():
    profile = make_profile(schedule_type="interval", schedule_value="60")
    assert is_profile_ready(profile, datetime.now(timezone.utc)) is True


def test_interval_profile_waits_until_interval_elapsed():
    now = datetime(2026, 9, 17, 12, 0, tzinfo=timezone.utc)
    profile = make_profile(schedule_type="interval", schedule_value="60", last_run_at=datetime(2026, 9, 17, 11, 30, tzinfo=timezone.utc))
    assert is_profile_ready(profile, now) is False


def test_daily_profile_uses_local_time():
    now = datetime(2026, 9, 17, 13, 30, tzinfo=timezone.utc)
    profile = make_profile(schedule_type="daily", schedule_value="09:30", timezone="America/New_York")
    assert is_profile_ready(profile, now) is True


def test_regeneration_bypasses_schedule():
    now = datetime(2026, 9, 17, 12, 0, tzinfo=timezone.utc)
    profile = make_profile(schedule_type="daily", schedule_value="23:00", timezone="UTC", regeneration_requested_at=datetime(2026, 9, 17, 11, 59, tzinfo=timezone.utc))
    assert is_profile_ready(profile, now) is True
