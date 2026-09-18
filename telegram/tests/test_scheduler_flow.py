import pytest

from src import scheduler


class FakeResponse:
    def __init__(self, payload, status_code=200):
        self._payload = payload
        self.status_code = status_code

    def json(self):
        return self._payload

    def raise_for_status(self):
        if self.status_code >= 400:
            raise RuntimeError(f"HTTP {self.status_code}")


@pytest.mark.asyncio
async def test_generate_and_send_profile_completes_notification_only_after_delivery(monkeypatch):
    calls = []

    async def claim_profile_run(profile_id, *, force=False):
        calls.append(("claim", profile_id, force))
        return {"id": 101}

    async def backend_request(method, path, json=None):
        calls.append(("request", method, path, json))
        return FakeResponse({"id": 501, "content_id": 601})

    async def fetch_collection(path):
        calls.append(("fetch", path))
        return [{
            "id": 601,
            "title": "Autonomous topic",
            "body": "A publication-ready post with enough substance.",
            "language": "en",
        }]

    async def send_admin_message(bot, text, admins, reply_markup=None):
        calls.append(("send", admins, reply_markup))
        return True

    async def complete_notification(content_id):
        calls.append(("complete", content_id))

    monkeypatch.setattr(scheduler, "claim_profile_run", claim_profile_run)
    monkeypatch.setattr(scheduler, "backend_request", backend_request)
    monkeypatch.setattr(scheduler, "fetch_collection", fetch_collection)
    monkeypatch.setattr(scheduler, "send_admin_message", send_admin_message)
    monkeypatch.setattr(scheduler, "complete_notification", complete_notification)
    monkeypatch.setattr(scheduler, "approval_keyboard", lambda content_id, profile_id: ("keyboard", content_id, profile_id))

    profile = {
        "id": 7,
        "name": "Daily Tech",
        "workspace_id": 11,
        "language": "en",
    }

    result = await scheduler.generate_and_send_profile(object(), profile, [42])

    assert result is True
    assert ("claim", 7, False) in calls
    assert ("request", "POST", "/content/profiles/7/generate", {}) in calls
    assert ("complete", 601) in calls
    assert calls.index(("send", [42], ("keyboard", 601, 7))) < calls.index(("complete", 601))


@pytest.mark.asyncio
async def test_generate_and_send_profile_keeps_notification_retryable_when_delivery_fails(monkeypatch):
    completed = []

    async def claim_profile_run(profile_id, *, force=False):
        return {"id": 101}

    async def backend_request(method, path, json=None):
        return FakeResponse({"id": 501, "content_id": 601})

    async def fetch_collection(path):
        return [{
            "id": 601,
            "title": "Autonomous topic",
            "body": "A publication-ready post with enough substance.",
            "language": "en",
        }]

    async def send_admin_message(bot, text, admins, reply_markup=None):
        return False

    async def complete_notification(content_id):
        completed.append(content_id)

    monkeypatch.setattr(scheduler, "claim_profile_run", claim_profile_run)
    monkeypatch.setattr(scheduler, "backend_request", backend_request)
    monkeypatch.setattr(scheduler, "fetch_collection", fetch_collection)
    monkeypatch.setattr(scheduler, "send_admin_message", send_admin_message)
    monkeypatch.setattr(scheduler, "complete_notification", complete_notification)
    monkeypatch.setattr(scheduler, "approval_keyboard", lambda content_id, profile_id: None)

    profile = {"id": 7, "name": "Daily Tech", "workspace_id": 11, "language": "en"}

    result = await scheduler.generate_and_send_profile(object(), profile, [42])

    assert result is False
    assert completed == []


@pytest.mark.parametrize(
    ("raw", "expected"),
    [
        ("TOPIC: AI news\nPOST: Useful update", ("AI news", "Useful update")),
        ("TOPIC: AI news\nMESSAGE: Useful update", ("AI news", "Useful update")),
        ("Topic without marker", None),
    ],
)
def test_parse_generation_output_is_strict_about_structured_output(raw, expected):
    assert scheduler.parse_generation_output(raw) == expected
