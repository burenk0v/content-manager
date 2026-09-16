from tests.test_foundation_api import HEADERS, client


def make_content():
    import uuid

    suffix = uuid.uuid4().hex[:8]
    workspace = client.post(
        "/content/workspaces",
        json={"name": f"Lifecycle {suffix}", "slug": f"lifecycle-{suffix}"},
        headers=HEADERS,
    )
    assert workspace.status_code == 201
    content = client.post(
        "/content/contents",
        json={
            "workspace_id": workspace.json()["id"],
            "body": "Lifecycle test",
            "language": "en",
            "source": "human",
        },
        headers=HEADERS,
    )
    assert content.status_code == 201
    return content.json()["id"]


def transition(content_id, target):
    return client.post(
        f"/content/contents/{content_id}/transition",
        json={"status": target},
        headers=HEADERS,
    )


def test_content_lifecycle_allows_valid_flow():
    content_id = make_content()
    for target in ("review", "approved", "scheduled", "publishing", "published", "archived"):
        response = transition(content_id, target)
        assert response.status_code == 200
        assert response.json()["status"] == target


def test_content_lifecycle_rejects_invalid_transition():
    content_id = make_content()
    response = transition(content_id, "published")
    assert response.status_code == 409


def test_content_lifecycle_exposes_allowed_transitions():
    content_id = make_content()
    response = client.get(f"/content/contents/{content_id}/transitions", headers=HEADERS)
    assert response.status_code == 200
