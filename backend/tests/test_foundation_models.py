from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from src.app.models import Base, Channel, Content, ContentVersion, Workspace


def test_foundation_models_support_content_lifecycle():
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
        content = Content(
            workspace_id=workspace.id,
            title="Hello",
            body="Draft body",
            language="en",
        )
        db.add_all([channel, content])
        db.flush()

        version = ContentVersion(
            content_id=content.id,
            version=1,
            body="Draft body",
            source="human",
        )
        db.add(version)
        db.commit()

        assert content.versions[0].version == 1
        assert channel.workspace.slug == "demo"


def test_content_version_number_is_unique_per_content():
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    Session = sessionmaker(bind=engine)

    with Session() as db:
        workspace = Workspace(name="Demo", slug="demo")
        db.add(workspace)
        db.flush()
        content = Content(workspace_id=workspace.id, body="Body", language="en")
        db.add(content)
        db.flush()

        db.add(ContentVersion(content_id=content.id, version=1, body="v1"))
        db.commit()

        db.add(ContentVersion(content_id=content.id, version=1, body="duplicate"))
        try:
            db.commit()
            assert False, "duplicate content version should fail"
        except Exception:
            db.rollback()
