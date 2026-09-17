from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from src.app.models import Base, Channel, ContentProfile, Workspace


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
