import pytest

from scheduler import retry_pending_notifications


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
async def test_pending_review_notification_is_delivered(monkeypatch):
    monkeypatch.setattr("scheduler.CALLBACK_SECRET", "test-secret")
    bot = FakeBot()
    calls = []

    async def backend_request(method, path, json=None):
        calls.append((method, path, json))
        if path == "/content/contents/42/notification-claim":
            return FakeResponse({"id": 42, "status": "review", "claim_token": "claim-42"})
        if path == "/content/contents/42/notification-complete":
            return FakeResponse({"id": 42, "status": "review"})
        raise AssertionError((method, path, json))

    async def contents(path):
        return [{
            "id": 42,
            "profile_id": 7,
            "title": "Test topic",
            "body": "This is a complete test post with enough content.",
            "language": "en",
            "status": "review",
        }]

    async def profile(profile_id):
        return {"id": 7, "name": "Test profile", "language": "en", "is_active": True}

    monkeypatch.setattr("scheduler.backend_request", backend_request)
    monkeypatch.setattr("scheduler.fetch_collection", contents)
    monkeypatch.setattr("scheduler.fetch_profile", profile)

    await retry_pending_notifications(bot, [1001])

    assert calls[0] == ("POST", "/content/contents/42/notification-claim", None)
    assert calls[1] == ("POST", "/content/contents/42/notification-complete", {"claim_token": "claim-42"})
    assert bot.calls and bot.calls[0][0] == 1001
    assert "Test topic" in bot.calls[0][1]
    assert bot.calls[0][3] is not None
