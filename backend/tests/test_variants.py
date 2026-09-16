import uuid

from src.app.models import ContentVariant
from tests.test_foundation_api import HEADERS, client, engine, TestingSession


class FakeTransformer:
    name = "fake"

    def transform(self, request):
        return f"[{request.platform}] {request.body}"


def create_content_and_channel():
    suffix = uuid.uuid4().hex[:8]
    workspace = client.post(
        "/content/workspaces",
        json={"name": f"Variants {suffix}", "slug": f"variants-{suffix}"},
        headers=HEADERS,
    ).json()
    channel = client.post(
        "/content/channels",
        json={
            "workspace_id": workspace["id"],
            "platform": "telegram",
            "external_id": f"@variants_{suffix}",
        },
        headers=HEADERS,
    ).json()
    content = client.post(
        "/content/contents",
        json={"workspace_id": workspace["id"], "body": "Canonical text", "language": "en"},
        headers=HEADERS,
    ).json()
    return content, channel


def test_transform_creates_channel_variant_without_mutating_source(monkeypatch):
    content, channel = create_content_and_channel()
    monkeypatch.setattr("src.app.routers.variants.get_content_transformer", lambda: FakeTransformer())

    source_version_id = client.get(
        f"/content/contents/{content['id']}/versions", headers=HEADERS
    ).json()[0]["id"]

    response = client.post(
        f"/content/contents/{content['id']}/variants/{channel['id']}/transform",
        json={"instructions": "Keep it concise"},
        headers=HEADERS,
    )
    assert response.status_code == 201
    variant = response.json()
    assert variant["content_id"] == content["id"]
    assert variant["content_version_id"] == source_version_id
    assert variant["version"] == 1
    assert variant["body"] == "[telegram] Canonical text"
    assert variant["status"] == "draft"

    source = client.get(f"/content/contents/{content['id']}", headers=HEADERS)
    assert source.status_code == 200
    assert source.json()["body"] == "Canonical text"


def test_retransform_is_versioned_and_preserves_history(monkeypatch):
    content, channel = create_content_and_channel()
    monkeypatch.setattr("src.app.routers.variants.get_content_transformer", lambda: FakeTransformer())

    path = f"/content/contents/{content['id']}/variants/{channel['id']}/transform"
    first = client.post(path, json={}, headers=HEADERS)
    second = client.post(path, json={"instructions": "Make it punchier"}, headers=HEADERS)
    assert first.status_code == 201
    assert second.status_code == 201
    assert second.json()["version"] == 2

    variants = client.get(
        f"/content/contents/{content['id']}/variants?channel_id={channel['id']}",
        headers=HEADERS,
    )
    assert variants.status_code == 200
    assert [item["version"] for item in variants.json()] == [2, 1]


def test_variant_cannot_use_version_from_another_content(monkeypatch):
    content, channel = create_content_and_channel()
    other, _ = create_content_and_channel()
    monkeypatch.setattr("src.app.routers.variants.get_content_transformer", lambda: FakeTransformer())

    other_version_id = client.get(
        f"/content/contents/{other['id']}/versions", headers=HEADERS
    ).json()[0]["id"]
    response = client.post(
        f"/content/contents/{content['id']}/variants/{channel['id']}/transform",
        json={"content_version_id": other_version_id},
        headers=HEADERS,
    )
    assert response.status_code == 404


def test_variant_failure_does_not_persist_partial_row(monkeypatch):
    content, channel = create_content_and_channel()

    class BrokenTransformer:
        name = "broken"

        def transform(self, request):
            raise RuntimeError("provider failed")

    monkeypatch.setattr("src.app.routers.variants.get_content_transformer", lambda: BrokenTransformer())
    response = client.post(
        f"/content/contents/{content['id']}/variants/{channel['id']}/transform",
        json={},
        headers=HEADERS,
    )
    assert response.status_code == 502

    db = TestingSession()
    try:
        assert db.query(ContentVariant).filter(ContentVariant.content_id == content["id"]).count() == 0
    finally:
        db.close()
