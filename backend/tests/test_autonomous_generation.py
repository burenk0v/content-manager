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


def test_unexpected_generation_failure_is_persisted(monkeypatch):
    profile = create_profile()

    class ExplodingProvider:
        name = "fake"

        def generate(self, *, prompt, system_message, model):
            raise RuntimeError("unexpected provider failure")

    monkeypatch.setattr("src.app.services.generation_service.get_generation_provider", lambda: ExplodingProvider())
    response = client.post(f"/content/profiles/{profile['id']}/generate", headers=HEADERS)
    assert response.status_code == 502

    contents = client.get(f"/content/contents?workspace_id={profile['workspace_id']}", headers=HEADERS)
    generated = next(item for item in contents.json() if item["title"] == "AI generation in progress")
    generations = client.get(f"/content/contents/{generated['id']}/generations", headers=HEADERS)
    assert generations.json()[0]["status"] == "failed"


def test_autonomous_generation_approval_publication_flow(monkeypatch):
    profile = create_profile()

    class FakeProvider:
        name = "fake"

        def generate(self, *, prompt, system_message, model):
            return (
                "TOPIC: Durable worker leases\n"
                "POST: Durable leases let background workers recover safely after restarts and avoid duplicate processing."
            )

    monkeypatch.setattr(
        "src.app.services.generation_service.get_generation_provider",
        lambda: FakeProvider(),
    )

    generated = client.post(
        f"/content/profiles/{profile['id']}/generate",
        headers=HEADERS,
    )
    assert generated.status_code == 201
    run = generated.json()

    to_review = client.post(
        f"/content/contents/{run['content_id']}/transition",
        json={"status": "review"},
        headers=HEADERS,
    )
    assert to_review.status_code == 200

    approved = client.post(
        f"/content/contents/{run['content_id']}/approve-and-schedule",
        json={"content_id": run["content_id"], "channel_id": profile["channel_id"]},
        headers=HEADERS,
    )
    assert approved.status_code == 201
    publication = approved.json()
    assert publication["status"] == "scheduled"

    claimed = client.post(
        f"/content/publications/{publication['id']}/claim",
        json={"worker_id": "e2e-worker"},
        headers=HEADERS,
    )
    assert claimed.status_code == 200
    token = claimed.json()["processing_token"]

    completed = client.post(
        f"/content/publications/{publication['id']}/complete",
        json={
            "worker_id": "e2e-worker",
            "processing_token": token,
            "external_id": "telegram:test-1",
        },
        headers=HEADERS,
    )
    assert completed.status_code == 200
    assert completed.json()["status"] == "published"

    snapshot = client.get(
        f"/content/contents/{run['content_id']}/transitions",
        headers=HEADERS,
    )
    assert snapshot.status_code == 200
    assert snapshot.json()["status"] == "published"


def test_autonomous_generation_reuses_failed_content_after_restart(monkeypatch):
    profile = create_profile()
    calls = []

    class RestartingProvider:
        name = "fake"

        def generate(self, *, prompt, system_message, model):
            calls.append(prompt)
            if len(calls) == 1:
                from src.app.ai_generation import GenerationError
                raise GenerationError("simulated worker restart")
            return (
                "TOPIC: Recoverable Python worker\n"
                "POST: Persisting generation state lets a restarted worker continue the same editorial task instead of creating unrelated content."
            )

    monkeypatch.setattr(
        "src.app.services.generation_service.get_generation_provider",
        lambda: RestartingProvider(),
    )

    first = client.post(f"/content/profiles/{profile['id']}/generate", headers=HEADERS)
    assert first.status_code == 502

    contents = client.get(
        f"/content/contents?workspace_id={profile['workspace_id']}",
        headers=HEADERS,
    )
    assert contents.status_code == 200
    in_progress = next(
        item for item in contents.json()
        if item["title"] == "AI generation in progress"
    )
    content_id = in_progress["id"]

    generations = client.get(
        f"/content/contents/{content_id}/generations",
        headers=HEADERS,
    )
    assert generations.status_code == 200
    assert generations.json()[0]["status"] == "failed"

    second = client.post(f"/content/profiles/{profile['id']}/generate", headers=HEADERS)
    assert second.status_code == 201
    run = second.json()
    assert run["content_id"] == content_id
    assert run["status"] == "succeeded"
    assert len(calls) == 2
    assert calls[1] == calls[0]

    contents = client.get(
        f"/content/contents?workspace_id={profile['workspace_id']}",
        headers=HEADERS,
    )
    generated = next(item for item in contents.json() if item["id"] == content_id)
    assert generated["title"] == "Recoverable Python worker"


def test_topic_memory_rejects_close_rephrasing():
    from src.app.services.topic_memory import find_duplicate_topic

    memory = [("Asyncio gather for parallel tasks", "published")]
    duplicate = find_duplicate_topic("Parallel execution with asyncio.gather", memory)
    assert duplicate is not None
    assert duplicate[0] == "Asyncio gather for parallel tasks"
    assert duplicate[1] == "published"


def test_autonomous_generation_rejects_duplicate_topic_and_recovers_with_new_prompt(monkeypatch):
    profile = create_profile()
    calls = []
    outputs = [
        "TOPIC: Asyncio gather for parallel tasks\nPOST: asyncio.gather combines awaitables and returns their results in order.",
        "TOPIC: Parallel execution with asyncio.gather\nPOST: This is a rephrasing of an already published topic and must be rejected.",
        "TOPIC: Python structural pattern matching\nPOST: Structural pattern matching with match and case can make complex branching easier to read.",
    ]

    class TopicProvider:
        name = "fake"

        def generate(self, *, prompt, system_message, model):
            calls.append(prompt)
            return outputs.pop(0)

    monkeypatch.setattr(
        "src.app.services.generation_service.get_generation_provider",
        lambda: TopicProvider(),
    )

    first = client.post(f"/content/profiles/{profile['id']}/generate", headers=HEADERS)
    assert first.status_code == 201

    duplicate = client.post(f"/content/profiles/{profile['id']}/generate", headers=HEADERS)
    assert duplicate.status_code == 502

    contents = client.get(
        f"/content/contents?workspace_id={profile['workspace_id']}",
        headers=HEADERS,
    )
    titles = [item["title"] for item in contents.json()]
    assert titles.count("Asyncio gather for parallel tasks") == 1
    assert "Parallel execution with asyncio.gather" not in titles

    third = client.post(f"/content/profiles/{profile['id']}/generate", headers=HEADERS)
    assert third.status_code == 201
    assert len(calls) == 3
    assert calls[1] == calls[2]

    contents = client.get(
        f"/content/contents?workspace_id={profile['workspace_id']}",
        headers=HEADERS,
    )
    titles = [item["title"] for item in contents.json()]
    assert "Python structural pattern matching" in titles

    generations = client.get(
        f"/content/contents/{first.json()['content_id']}/generations",
        headers=HEADERS,
    )
    assert generations.status_code == 200
    assert generations.json()[0]["status"] == "succeeded"
