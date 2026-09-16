from tests.test_foundation_api import HEADERS, client


def make_content() -> int:
    import uuid

    workspace = client.post(
        "/content/workspaces",
        json={"name": f"AI Workspace {uuid.uuid4().hex[:8]}", "slug": f"ai-{uuid.uuid4().hex[:8]}"},
        headers=HEADERS,
    )
    assert workspace.status_code == 201
    content = client.post(
        "/content/contents",
        json={
            "workspace_id": workspace.json()["id"],
            "title": "AI test",
            "body": "Original",
            "language": "en",
        },
        headers=HEADERS,
    )
    assert content.status_code == 201
    return content.json()["id"]


def test_generate_creates_version_and_invalidates_approval(monkeypatch):
    content_id = make_content()
    transition = client.post(
        f"/content/contents/{content_id}/transition",
        json={"status": "review"},
        headers=HEADERS,
    )
    assert transition.status_code == 200
    transition = client.post(
        f"/content/contents/{content_id}/transition",
        json={"status": "approved"},
        headers=HEADERS,
    )
    assert transition.status_code == 200

    class FakeProvider:
        name = "fake"

        def generate(self, *, prompt, system_message, model):
            assert prompt == "Create a better post"
            return "Generated version"

    monkeypatch.setattr("src.app.services.generation_service.get_generation_provider", lambda: FakeProvider())
    response = client.post(
        f"/content/contents/{content_id}/generate",
        json={"prompt": "Create a better post", "model": "fake-model"},
        headers=HEADERS,
    )
    assert response.status_code == 201
    run = response.json()
    assert run["status"] == "succeeded"
    assert run["provider"] == "fake"
    assert run["content_version_id"] is not None

    content = client.get("/content/contents", headers=HEADERS).json()
    item = next(row for row in content if row["id"] == content_id)
    assert item["status"] == "draft"
    versions = client.get(f"/content/contents/{content_id}/versions", headers=HEADERS)
    assert versions.status_code == 200
    assert versions.json()[0]["body"] == "Generated version"


def test_generation_failure_is_recorded(monkeypatch):
    content_id = make_content()

    class FailingProvider:
        name = "fake"

        def generate(self, *, prompt, system_message, model):
            from src.app.ai_generation import GenerationError
            raise GenerationError("temporary provider failure")

    monkeypatch.setattr("src.app.services.generation_service.get_generation_provider", lambda: FailingProvider())
    response = client.post(
        f"/content/contents/{content_id}/generate",
        json={"prompt": "Generate"},
        headers=HEADERS,
    )
    assert response.status_code == 502
    runs = client.get(f"/content/contents/{content_id}/generations", headers=HEADERS)
    assert runs.status_code == 200
    assert runs.json()[0]["status"] == "failed"
    assert runs.json()[0]["error_message"] == "temporary provider failure"
