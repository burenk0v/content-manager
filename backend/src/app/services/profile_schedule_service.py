from datetime import datetime, timezone
from zoneinfo import ZoneInfo

from src.app.models import ContentProfile


def is_profile_ready(profile: ContentProfile, now_utc: datetime) -> bool:
    if not profile.is_active or profile.regeneration_requested:
        return True

    last_run = profile.last_run.replace(tzinfo=timezone.utc) if profile.last_run else None

    if profile.schedule_type == "interval":
        try:
            minutes = int(profile.schedule_value)
        except ValueError:
            return False
        if minutes <= 0:
            return False
        return last_run is None or (now_utc - last_run).total_seconds() >= minutes * 60

    try:
        hour, minute = (int(value) for value in profile.schedule_value.split(":", 1))
        if not 0 <= hour <= 23 or not 0 <= minute <= 59:
            return False
        local_now = now_utc.astimezone(ZoneInfo(profile.timezone))
    except (ValueError, TypeError, KeyError):
        return False

    if last_run is not None and last_run.astimezone(ZoneInfo(profile.timezone)).date() == local_now.date():
        return False
    return (local_now.hour, local_now.minute) >= (hour, minute)
