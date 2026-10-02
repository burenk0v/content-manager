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


def topic_then_post(topic, post):
    calls = []

    class Provider:
        name = "fake"

        def generate(self, *, prompt, system_message, model):
            calls.append((prompt, system_message))
            if "select unique publication topics" in system_message:
                return f"TOPIC: {topic}"
            return f"POST: {post}"

    return Provider(), calls


def test_autonomous_profile_generation_persists_run_and_version(monkeypatch):
    profile = create_profile()
    provider, calls = topic_then_post(
        "Reliable background jobs",
        "Use durable state and leases for long-running jobs. This makes worker restarts recoverable and prevents duplicate processing.",
    )
    monkeypatch.setattr("src.app.services.generation_service.get_generation_provider", lambda: provider)

    response = client.post(f"/content/profiles/{profile['id']}/generate", headers=HEADERS)
    assert response.status_code == 201
    run = response.json()
    assert run["status"] == "succeeded"
    assert run["provider"] == "fake"
    assert run["content_version_id"] is not None
    assert len(calls) == 2
    assert "Topic memory" not in calls[0][0]

    contents = client.get(f"/content/contents?workspace_id={profile['workspace_id']}", headers=HEADERS)
    generated = next(item for item in contents.json() if item["id"] == run["content_id"])
    assert generated["title"] == "Reliable background jobs"
    assert generated["status"] == "review"

    versions = client.get(f"/content/contents/{run['content_id']}/versions", headers=HEADERS)
    assert versions.json()[0]["body"].startswith("Use durable state and leases")


def test_autonomous_profile_generation_records_provider_failure(monkeypatch):
    profile = create_profile()

    class FailingProvider:
        name = "fake"

        def generate(self, *, prompt, system_message, model):
            from src.app.ai_generation import GenerationError
            raise GenerationError("provider unavailable")

    monkeypatch.setattr("src.app.services.generation_service.get_generation_provider", lambda: FailingProvider())
    response = client.post(f"/content/profiles/{profile['id']}/generate", headers=HEADERS)
    assert response.status_code == 502


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
    provider, _ = topic_then_post(
        "Durable worker leases",
        "Durable leases let background workers recover safely after restarts and avoid duplicate processing.",
    )
    monkeypatch.setattr("src.app.services.generation_service.get_generation_provider", lambda: provider)

    generated = client.post(f"/content/profiles/{profile['id']}/generate", headers=HEADERS)
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
        json={"worker_id": "e2e-worker", "processing_token": token, "external_id": "telegram:test-1"},
        headers=HEADERS,
    )
    assert completed.status_code == 200
    assert completed.json()["status"] == "published"


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
            if "select unique publication topics" in system_message:
                return "TOPIC: Recoverable Python worker"
            return "POST: Persisting generation state lets a restarted worker continue the same editorial task instead of creating unrelated content."

    monkeypatch.setattr("src.app.services.generation_service.get_generation_provider", lambda: RestartingProvider())

    first = client.post(f"/content/profiles/{profile['id']}/generate", headers=HEADERS)
    assert first.status_code == 502

    contents = client.get(f"/content/contents?workspace_id={profile['workspace_id']}", headers=HEADERS)
    in_progress = next(item for item in contents.json() if item["title"] == "AI generation in progress")
    content_id = in_progress["id"]

    second = client.post(f"/content/profiles/{profile['id']}/generate", headers=HEADERS)
    assert second.status_code == 201
    assert second.json()["content_id"] == content_id
    assert len(calls) == 3


def test_topic_memory_rejects_close_rephrasing():
    from src.app.services.topic_memory import find_duplicate_topic

    memory = [("Asyncio gather for parallel tasks", "published")]
    duplicate = find_duplicate_topic("Parallel execution with asyncio.gather", memory)
    assert duplicate is not None
    assert duplicate[0] == "Asyncio gather for parallel tasks"
    assert duplicate[1] == "published"


def test_autonomous_generation_retries_duplicate_topic_until_unique(monkeypatch):
    profile = create_profile()
    calls = []
    topics = [
        "Asyncio gather for parallel tasks",
        "Parallel execution with asyncio.gather",
        "Python structural pattern matching",
    ]

    class TopicProvider:
        name = "fake"

        def generate(self, *, prompt, system_message, model):
            calls.append(prompt)
            if "select unique publication topics" in system_message:
                return f"TOPIC: {topics.pop(0)}"
            return "POST: Structural pattern matching with match and case can make complex branching easier to read."

    monkeypatch.setattr("src.app.services.generation_service.get_generation_provider", lambda: TopicProvider())

    first = client.post(f"/content/profiles/{profile['id']}/generate", headers=HEADERS)
    assert first.status_code == 201

    second = client.post(f"/content/profiles/{profile['id']}/generate", headers=HEADERS)
    assert second.status_code == 201

    assert len(calls) == 5
    assert "Asyncio gather for parallel tasks" not in calls[2]
    assert "Asyncio gather for parallel tasks" in calls[3]
    assert "Selected topic: Python structural pattern matching" in calls[4]

    contents = client.get(f"/content/contents?workspace_id={profile['workspace_id']}", headers=HEADERS)
    titles = [item["title"] for item in contents.json()]
    assert titles.count("Asyncio gather for parallel tasks") == 1
    assert "Python structural pattern matching" in titles


def test_python_quality_accepts_valid_python_block():
    from src.app.services.python_quality import validate_post

    report = validate_post("Use this helper:\n\n```python\ndef add(a: int, b: int) -> int:\n    return a + b\n```")
    assert report.checked is True
    assert report.valid is True
    assert report.issues == ()


def test_python_quality_rejects_invalid_python_block():
    from src.app.services.python_quality import validate_post

    report = validate_post("Broken example:\n\n```python\ndef add(a, b)\n    return a + b\n```")
    assert report.checked is True
    assert report.valid is False
    assert report.issues[0].code == "syntax_error"


def test_autonomous_generation_rejects_invalid_python_before_persistence(monkeypatch):
    profile = create_profile()

    class InvalidPythonProvider:
        name = "fake"

        def generate(self, *, prompt, system_message, model):
            if "select unique publication topics" in system_message:
                return "TOPIC: Python syntax pitfalls"
            return "POST: Check this example.\n\n```python\ndef broken(x)\n    return x\n```"

    monkeypatch.setattr("src.app.services.generation_service.get_generation_provider", lambda: InvalidPythonProvider())
    response = client.post(f"/content/profiles/{profile['id']}/generate", headers=HEADERS)
    assert response.status_code == 502


def test_python_sandbox_client_round_trip(monkeypatch, tmp_path):
    import json
    import threading
    import time
    from src.app.services.python_sandbox import execute_python_blocks

    root = tmp_path / "validator"
    inbox = root / "inbox"
    outbox = root / "outbox"
    inbox.mkdir(parents=True)
    outbox.mkdir(parents=True)
    monkeypatch.setenv("PYTHON_VALIDATOR_DIR", str(root))
    monkeypatch.setenv("PYTHON_VALIDATOR_TIMEOUT_SECONDS", "2")

    def worker():
        deadline = time.monotonic() + 2
        while time.monotonic() < deadline:
            jobs = list(inbox.glob("*.json"))
            if jobs:
                job = jobs[0]
                payload = json.loads(job.read_text())
                assert "print('ok')" in payload["code"]
                (outbox / job.name).write_text(json.dumps({"ok": True}))
                return
            time.sleep(0.01)
        raise AssertionError("sandbox request was not created")

    thread = threading.Thread(target=worker)
    thread.start()
    execute_python_blocks(["print('ok')"])
    thread.join(timeout=2)
    assert not thread.is_alive()


def test_python_sandbox_client_surfaces_validator_failure(monkeypatch, tmp_path):
    import json
    import threading
    import time
    import pytest
    from src.app.services.python_sandbox import PythonSandboxError, execute_python_blocks

    root = tmp_path / "validator"
    inbox = root / "inbox"
    outbox = root / "outbox"
    inbox.mkdir(parents=True)
    outbox.mkdir(parents=True)
    monkeypatch.setenv("PYTHON_VALIDATOR_DIR", str(root))
    monkeypatch.setenv("PYTHON_VALIDATOR_TIMEOUT_SECONDS", "2")

    def worker():
        deadline = time.monotonic() + 2
        while time.monotonic() < deadline:
            jobs = list(inbox.glob("*.json"))
            if jobs:
                tmp = outbox / (".tmp-" + jobs[0].name)
                tmp.write_text(json.dumps({"ok": False, "error": "execution failed"}))
                tmp.replace(outbox / jobs[0].name)
                return
            time.sleep(0.01)
        raise AssertionError("sandbox request was not created")

    thread = threading.Thread(target=worker)
    thread.start()
    with pytest.raises(PythonSandboxError, match="execution failed"):
        execute_python_blocks(["raise RuntimeError('boom')"])
    thread.join(timeout=2)
    assert not thread.is_alive()
