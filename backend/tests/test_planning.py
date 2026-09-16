from tests.test_foundation_api import HEADERS, client


def make_content(status: str = "draft") -> int:
    import uuid

    suffix = uuid.uuid4().hex[:8]
    workspace = client.post("/content/workspaces", json={"name": f"Planning {suffix}", "slug": f"planning-{suffix}"}, headers=HEADERS).json()
    content = client.post("/content/contents", json={"workspace_id": workspace["id"], "title": "Planning", "body": "Body", "language": "en"}, headers=HEADERS).json()
    if status == "draft":
        return content["id"]
    client.post(f"/content/contents/{content['id']}/transition", json={"status": "review"}, headers=HEADERS)
    if status == "review":
        return content["id"]
    client.post(f"/content/contents/{content['id']}/transition", json={"status": "approved"}, headers=HEADERS)
    if status == "approved":
        return content["id"]
    raise ValueError(status)


def test_workflow_snapshot_exposes_state_and_publication_counts() -> None:
    content_id = make_content("approved")
    response = client.get(f"/content/contents/{content_id}/workflow", headers=HEADERS)
    assert response.status_code == 200
    data = response.json()
    assert data["status"] == "approved"
    assert data["current_version"] == 1
    assert "scheduled" in data["allowed_transitions"]
    assert data["publication_counts"] == {}


def test_bulk_transition_is_atomic_on_invalid_transition() -> None:
    first = make_content("draft")
    second = make_content("draft")
    response = client.post(
        "/content/contents/bulk-transition",
        json={"items": [{"content_id": first, "status": "review"}, {"content_id": second, "status": "published"}]},
        headers=HEADERS,
    )
    assert response.status_code == 409
    assert client.get(f"/content/contents/{first}/workflow", headers=HEADERS).json()["status"] == "draft"
    assert client.get(f"/content/contents/{second}/workflow", headers=HEADERS).json()["status"] == "draft"


def test_bulk_transition_updates_multiple_contents() -> None:
    first = make_content("draft")
    second = make_content("draft")
    response = client.post(
        "/content/contents/bulk-transition",
        json={"items": [{"content_id": first, "status": "review"}, {"content_id": second, "status": "review"}]},
        headers=HEADERS,
    )
    assert response.status_code == 200
    assert [item["status"] for item in response.json()] == ["review", "review"]
