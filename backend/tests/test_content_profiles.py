from datetime import datetime, timezone

from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from src.app.models import Base, Channel, ContentProfile, Workspace
from src.app.routers.profiles import is_ready


def test_content_profile_persists_generation_and_schedule_configuration():
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    Session = sessionmaker(bind=engine)

    with Session() as db:
        workspace = Workspace(name="Demo", slug="demo")
        db.add(workspace)
        db.flush()
        channel = Channel(
            workspace_id=workspace.id,
            platform="telegram",
            external_id="-100123456789",
            name="Demo channel",
        )
        db.add(channel)
        db.flush()

        profile = ContentProfile(
            workspace_id=workspace.id,
            channel_id=channel.id,
            name="Daily tech",
            language="en",
            topic_niche="AI and developer tools",
            tone="Practical and concise",
            content_format="Short Telegram post with bullets",
            rules="No clickbait; explain acronyms; include a useful takeaway",
            timezone="America/New_York",
            schedule_type="daily",
            schedule_value="09:30",
            is_active=True,
        )
        db.add(profile)
        db.commit()
        db.refresh(profile)

        assert profile.channel.external_id == "-100123456789"
        assert profile.topic_niche == "AI and developer tools"
        assert profile.tone == "Practical and concise"
        assert profile.content_format == "Short Telegram post with bullets"
        assert profile.schedule_type == "daily"
        assert profile.is_active is True


def test_content_profile_name_is_unique_per_channel():
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    Session = sessionmaker(bind=engine)

    with Session() as db:
        workspace = Workspace(name="Demo", slug="demo")
        db.add(workspace)
        db.flush()
        channel = Channel(workspace_id=workspace.id, platform="telegram", external_id="-100123456789")
        db.add(channel)
        db.flush()
        db.add(ContentProfile(workspace_id=workspace.id, channel_id=channel.id, name="Daily", schedule_value="09:30"))
        db.commit()
        db.add(ContentProfile(workspace_id=workspace.id, channel_id=channel.id, name="Daily", schedule_value="10:00"))
        try:
            db.commit()
            assert False, "duplicate profile name should fail"
        except Exception:
            db.rollback()


def test_interval_profile_becomes_ready_after_interval():
    profile = ContentProfile(
        is_active=True,
        regeneration_requested=False,
        schedule_type="interval",
        schedule_value="60",
        last_run=datetime(2026, 9, 17, 8, 0),
    )
    now = datetime(2026, 9, 17, 9, 0, tzinfo=timezone.utc)
    assert is_ready(profile, now) is True


def test_daily_profile_runs_once_per_local_day():
    profile = ContentProfile(
        is_active=True,
        regeneration_requested=False,
        schedule_type="daily",
        schedule_value="09:30",
        timezone="America/New_York",
        last_run=datetime(2026, 9, 17, 13, 0),
    )
    same_day = datetime(2026, 9, 17, 14, 0, tzinfo=timezone.utc)
    next_day = datetime(2026, 9, 18, 14, 0, tzinfo=timezone.utc)
    assert is_ready(profile, same_day) is False
    assert is_ready(profile, next_day) is True


def test_regeneration_request_bypasses_schedule():
    profile = ContentProfile(
        is_active=True,
        regeneration_requested=True,
        schedule_type="daily",
        schedule_value="23:59",
        timezone="UTC",
        last_run=datetime(2026, 9, 17, 0, 0),
    )
    now = datetime(2026, 9, 17, 1, 0, tzinfo=timezone.utc)
    assert is_ready(profile, now) is True
