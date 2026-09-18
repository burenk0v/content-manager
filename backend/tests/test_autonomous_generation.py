from tests.test_foundation_api import HEADERS, client


def create_profile():
    import uuid
    suffix = uuid.uuid4().hex[:8]
    workspace = client.post(
        "/content/workspaces",
        json={"name": f"Autonomous {suffix}", "slug": f"autonomous-{suffix}"},
        headers=HEADERS,
    )
    assert workspace.status_code == 201
    workspace_id = workspace.json()["id"]
    channel = client.post(
        "/content/channels",
        json={
            "workspace_id": workspace_id,
            "platform": "telegram",
            "external_id": f"@autonomous_{suffix}",
            "name": "Autonomous channel",
        },
        headers=HEADERS,
    )
    assert channel.status_code == 201
    response = client.post(
        "/content/profiles",
        json={
            "workspace_id": workspace_id,
            "channel_id": channel.json()["id"],
            "name": "Autonomous profile",
            "language": "en",
            "topic_niche": "software engineering",
            "tone": "practical",
            "schedule_type": "interval",
            "schedule_value": "60",
            "timezone": "UTC",
        },
        headers=HEADERS,
    )
    assert response.status_code == 201
    return response.json()


def test_autonomous_profile_generation_persists_run_and_version(monkeypatch):
    profile = create_profile()

    class FakeProvider:
        name = "fake"

        def generate(self, *, prompt, system_message, model):
            assert "software engineering" in prompt
            assert "TOPIC:" in prompt
            return "TOPIC: Reliable background jobs\nPOST: Use durable state and leases for long-running jobs. This makes worker restarts recoverable and prevents duplicate processing."

    monkeypatch.setattr("src.app.services.generation_service.get_generation_provider", lambda: FakeProvider())
    response = client.post(
        f"/content/profiles/{profile['id']}/generate",
        headers=HEADERS,
    )
    assert response.status_code == 201
    run = response.json()
    assert run["status"] == "succeeded"
    assert run["provider"] == "fake"
    assert run["content_version_id"] is not None

    contents = client.get(
        f"/content/contents?workspace_id={profile['workspace_id']}",
        headers=HEADERS,
    )
    assert contents.status_code == 200
    generated = next(item for item in contents.json() if item["id"] == run["content_id"])
    assert generated["title"] == "Reliable background jobs"
    assert generated["status"] == "draft"

    versions = client.get(
        f"/content/contents/{run['content_id']}/versions",
        headers=HEADERS,
    )
    assert versions.status_code == 200
    assert versions.json()[0]["body"].startswith("Use durable state and leases")


def test_autonomous_profile_generation_records_provider_failure(monkeypatch):
    profile = create_profile()

    class FailingProvider:
        name = "fake"

        def generate(self, *, prompt, system_message, model):
            from src.app.ai_generation import GenerationError
            raise GenerationError("provider unavailable")

    monkeypatch.setattr("src.app.services.generation_service.get_generation_provider", lambda: FailingProvider())
    response = client.post(
        f"/content/profiles/{profile['id']}/generate",
        headers=HEADERS,
    )
    assert response.status_code == 502
    # The API returns an HTTP error body; inspect the persisted content and run instead.
    contents = client.get(
        f"/content/contents?workspace_id={profile['workspace_id']}",
        headers=HEADERS,
    )
    assert contents.status_code == 200
    generated = next(item for item in contents.json() if item["title"] == "AI generation in progress")
    generations = client.get(
        f"/content/contents/{generated['id']}/generations",
        headers=HEADERS,
    )
    assert generations.status_code == 200
    assert generations.json()[0]["status"] == "failed"
    assert generations.json()[0]["error_message"] == "provider unavailable"


def test_generation_heartbeat_updates_running_run(monkeypatch):
    import threading
    import time

    from src.app.services import generation_service

    calls = []

    class FakeQuery:
        def filter(self, *args):
            return self

        def first(self):
            calls.append("query")
            return type("Run", (), {"lease_heartbeat_at": None})()

    class FakeSession:
        def query(self, *args):
            return FakeQuery()

        def commit(self):
            calls.append("commit")

        def rollback(self):
            calls.append("rollback")

        def close(self):
            calls.append("close")

    monkeypatch.setattr(generation_service, "SessionLocal", lambda: FakeSession())
    monkeypatch.setattr(generation_service, "_generation_heartbeat_interval_seconds", lambda: 0.01)

    stop = threading.Event()
    worker = threading.Thread(target=generation_service._heartbeat_generation, args=(123, stop))
    worker.start()
    time.sleep(0.03)
    stop.set()
    worker.join(timeout=1)

    assert "query" in calls
    assert "commit" in calls
    assert "close" in calls
