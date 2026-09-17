import pytest

from scheduler import generate_and_send_profile


class FakeBot:
    def __init__(self):
        self.calls = []

    async def send_message(self, chat_id, text, parse_mode=None, reply_markup=None):
        self.calls.append((chat_id, text, parse_mode, reply_markup))
        return object()


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
async def test_autonomous_generation_reaches_telegram_review(monkeypatch):
    bot = FakeBot()
    profile = {
        "id": 7,
        "workspace_id": 1,
        "name": "Test profile",
        "language": "en",
    }
    calls = []

    async def claim(profile_id, *, force=False):
        calls.append(("claim", profile_id, force))
        return profile

    async def backend_request(method, path, json=None):
        calls.append(("request", method, path, json))
        if method == "POST" and path == "/content/profiles/7/generate":
            return FakeResponse({
                "id": 99,
                "content_id": 42,
                "content_version_id": 77,
                "status": "succeeded",
            })
        if method == "POST" and path == "/content/contents/42/notification-complete":
            return FakeResponse({"id": 42, "status": "review"})
        raise AssertionError((method, path, json))

    async def contents(workspace_id):
        return [{
            "id": 42,
            "profile_id": 7,
            "title": "Test topic",
            "body": "This is a complete test post with enough content.",
            "language": "en",
            "status": "review",
        }]

    monkeypatch.setattr("scheduler.claim_profile_run", claim)
    monkeypatch.setattr("scheduler.backend_request", backend_request)
    monkeypatch.setattr("scheduler.fetch_collection", contents)
    monkeypatch.setattr("scheduler.complete_notification", lambda content_id: backend_request(
        "POST", f"/content/contents/{content_id}/notification-complete"
    ))

    assert await generate_and_send_profile(bot, profile, [1001])
    assert calls[0] == ("claim", 7, False)
    assert ("request", "POST", "/content/profiles/7/generate", {}) in calls
    assert bot.calls and bot.calls[0][0] == 1001
    assert "Test topic" in bot.calls[0][1]
