from datetime import datetime, timedelta
from zoneinfo import ZoneInfo


def convert_local_time_to_utc(value: str, timezone_name: str) -> str:
    try:
        parsed_time = datetime.strptime(value, '%H:%M').time()
        reference_date = datetime.now(ZoneInfo(timezone_name)).date()
        local_dt = datetime.combine(reference_date, parsed_time, tzinfo=ZoneInfo(timezone_name))
        return local_dt.astimezone(ZoneInfo('UTC')).strftime('%H:%M')
    except Exception:
        return value


def convert_utc_time_to_local(value: str, timezone_name: str) -> str:
    try:
        parsed_time = datetime.strptime(value, '%H:%M').time()
        reference_date = datetime.now(ZoneInfo('UTC')).date()
        utc_dt = datetime.combine(reference_date, parsed_time, tzinfo=ZoneInfo('UTC'))
        return utc_dt.astimezone(ZoneInfo(timezone_name)).strftime('%H:%M')
    except Exception:
        return value


def convert_utc_datetime_to_local(value: str, timezone_name: str) -> str:
    try:
        utc_dt = datetime.fromisoformat(value.replace('Z', '+00:00'))
        if utc_dt.tzinfo is None:
            utc_dt = utc_dt.replace(tzinfo=ZoneInfo('UTC'))
        return utc_dt.astimezone(ZoneInfo(timezone_name)).strftime('%Y-%m-%d %H:%M')
    except Exception:
        return value


def compute_schedule_next_run_display(schedule: dict, timezone_name: str) -> str | None:
    next_run = schedule.get('next_run')
    if not next_run:
        return None

    if schedule.get('schedule_type') != 'daily':
        return convert_utc_datetime_to_local(next_run, timezone_name)

    try:
        timezone = ZoneInfo(timezone_name)
        now_local = datetime.now(timezone)
        local_run_time = datetime.strptime(
            convert_utc_time_to_local(schedule.get('schedule_value', ''), timezone_name),
            '%H:%M',
        ).time()
        local_last_run = None
        raw_last_run = schedule.get('last_run')
        if raw_last_run:
            local_last_run = datetime.fromisoformat(raw_last_run.replace('Z', '+00:00'))
            if local_last_run.tzinfo is None:
                local_last_run = local_last_run.replace(tzinfo=ZoneInfo('UTC'))
            local_last_run = local_last_run.astimezone(timezone)

        scheduled_local = datetime.combine(now_local.date(), local_run_time, tzinfo=timezone)
        if local_last_run is None or local_last_run.date() < now_local.date():
            if scheduled_local <= now_local:
                scheduled_local += timedelta(days=1)
        else:
            scheduled_local = datetime.combine(now_local.date() + timedelta(days=1), local_run_time, tzinfo=timezone)
        return scheduled_local.strftime('%Y-%m-%d %H:%M')
    except Exception:
        return convert_utc_datetime_to_local(next_run, timezone_name)
