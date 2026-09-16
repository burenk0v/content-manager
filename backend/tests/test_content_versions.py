import uuid

from test_foundation_api import HEADERS, TestingSession, client
from src.app.models import ContentVersion, Publication


def create_approved_content():
    suffix = uuid.uuid4().hex[:8]
    workspace = client.post("/content/workspaces", json={"name": f"Version {suffix}", "slug": f"version-{suffix}"}, headers=HEADERS).json()
    content = client.post(
        "/content/contents",
        json={"workspace_id": workspace["id"], "body": "v1", "language": "en"},
        headers=HEADERS,
    ).json()
    for target in ("review", "approved"):
        response = client.post(f"/content/contents/{content['id']}/transition", json={"status": target}, headers=HEADERS)
        assert response.status_code == 200
    return workspace["id"], content


def test_content_body_is_derived_from_latest_version():
    _, content = create_approved_content()
    assert content["body"] == "v1"

    version = client.post(
        f"/content/contents/{content['id']}/versions",
        json={"body": "v2", "source": "ai"},
        headers=HEADERS,
    )
    assert version.status_code == 201
    assert version.json()["version"] == 2

    listed = client.get(f"/content/contents/{content['id']}/versions", headers=HEADERS)
    assert [item["version"] for item in listed.json()] == [2, 1]
    current = client.get("/content/contents", headers=HEADERS)
    item = next(item for item in current.json() if item["id"] == content["id"])
    assert item["body"] == "v2"


def test_publication_pins_the_version_that_was_scheduled():
    workspace_id, content = create_approved_content()
    suffix = uuid.uuid4().hex[:8]
    channel = client.post(
        "/content/channels",
        json={"workspace_id": workspace_id, "platform": "telegram", "external_id": f"@pin_{suffix}"},
        headers=HEADERS,
    ).json()

    publication = client.post(
        "/content/publications",
        json={"content_id": content["id"], "channel_id": channel["id"], "idempotency_key": f"pin-{suffix}"},
        headers=HEADERS,
    )
    assert publication.status_code == 201
    assert publication.json()["content_version_id"] == content["id"] + 0 or publication.json()["content_version_id"] >= 1

    version = client.post(
        f"/content/contents/{content['id']}/versions",
        json={"body": "v2", "source": "human"},
        headers=HEADERS,
    )
    assert version.status_code == 201

    ready = client.get("/content/publications/ready", headers=HEADERS)
    pinned = next(item for item in ready.json() if item["id"] == publication.json()["id"])
    assert pinned["content_body"] == "v1"

    db = TestingSession()
    try:
        persisted = db.query(Publication).filter(Publication.id == publication.json()["id"]).one()
        assert persisted.content_version_id == version.json()["id"] - 1
        assert db.query(ContentVersion).filter(ContentVersion.id == persisted.content_version_id).one().body == "v1"
    finally:
        db.close()
