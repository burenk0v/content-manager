from datetime import datetime, timedelta

from tests.test_foundation_api import HEADERS, client
from src.app.models import Content, GenerationRun
from tests.test_foundation_api import TestingSession


def test_generation_blocks_duplicate_running_run(monkeypatch):
    from tests.test_autonomous_generation import create_profile
    profile = create_profile()
    class FakeProvider:
        name = "fake"
        def generate(self, *, prompt, system_message, model):
            return "TOPIC: Duplicate guard\nPOST: This generated post is long enough to pass validation and verify duplicate protection."
    monkeypatch.setattr("src.app.services.generation_service.get_generation_provider", lambda: FakeProvider())
    first = client.post(f"/content/profiles/{profile['id']}/generate", headers=HEADERS)
    assert first.status_code == 201
    run = first.json()
    db = TestingSession()
    try:
        content = db.query(Content).filter(Content.id == run["content_id"]).first()
        content.status = "draft"
        active = GenerationRun(content_id=content.id, provider="fake", model=None, status="running", prompt="in progress", lease_heartbeat_at=datetime.utcnow())
        db.add(active)
        db.commit()
    finally:
        db.close()
    response = client.post(f"/content/contents/{run['content_id']}/generate", json={"prompt":"retry"}, headers=HEADERS)
    assert response.status_code == 409


def test_stale_generation_recovery_requeues_profile(monkeypatch):
    from tests.test_autonomous_generation import create_profile
    profile = create_profile()
    db = TestingSession()
    try:
        content = Content(workspace_id=profile["workspace_id"], profile_id=profile["id"], title="stale", language="en", status="draft")
        db.add(content)
        db.flush()
        run = GenerationRun(content_id=content.id, provider="fake", status="running", prompt="stale", created_at=datetime.utcnow() - timedelta(hours=2), lease_heartbeat_at=datetime.utcnow() - timedelta(hours=2))
        db.add(run)
        db.commit()
        run_id = run.id
    finally:
        db.close()
    monkeypatch.setenv("GENERATION_LEASE_TIMEOUT_SECONDS", "60")
    response = client.post("/content/generations/recover-stale", headers=HEADERS)
    assert response.status_code == 200
    recovered = next(item for item in response.json() if item["id"] == run_id)
    assert recovered["status"] == "failed"
    assert "Recovered stale generation run" in recovered["error_message"]
    profile_response = client.get(f"/content/profiles/{profile['id']}", headers=HEADERS)
    assert profile_response.status_code == 200
    assert profile_response.json()["regeneration_requested"] is True


def test_profile_generation_auto_recovers_stale_run_and_reuses_content(monkeypatch):
    from tests.test_autonomous_generation import create_profile

    profile = create_profile()
    db = TestingSession()
    try:
        content = Content(
            workspace_id=profile["workspace_id"],
            profile_id=profile["id"],
            title="AI generation in progress",
            language="en",
            status="draft",
        )
        db.add(content)
        db.flush()
        prompt = "persisted autonomous prompt"
        run = GenerationRun(
            content_id=content.id,
            provider="fake",
            status="running",
            prompt=prompt,
            created_at=datetime.utcnow() - timedelta(hours=2),
            lease_heartbeat_at=datetime.utcnow() - timedelta(hours=2),
        )
        db.add(run)
        db.commit()
        content_id = content.id
    finally:
        db.close()

    monkeypatch.setenv("GENERATION_LEASE_TIMEOUT_SECONDS", "60")

    class RecoveringProvider:
        name = "fake"

        def generate(self, *, prompt, system_message, model):
            assert prompt == "persisted autonomous prompt"
            return (
                "TOPIC: Recovered stale work\n"
                "POST: The persisted generation task can be retried after a worker restart without creating a second content item."
            )

    monkeypatch.setattr(
        "src.app.services.generation_service.get_generation_provider",
        lambda: RecoveringProvider(),
    )

    response = client.post(f"/content/profiles/{profile['id']}/generate", headers=HEADERS)
    assert response.status_code == 201
    assert response.json()["content_id"] == content_id
    db = TestingSession()
    try:
        recovered_content = db.query(Content).filter(Content.id == content_id).first()
        assert recovered_content.status == "review"
    finally:
        db.close()
