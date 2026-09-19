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
async def test_notification_is_completed_only_after_delivery(monkeypatch):
    calls = []

    async def backend_request(method, path, json=None):
        calls.append((method, path, json))
        if path.endswith("/notification-claim"):
            return FakeResponse({"id": 601, "status": "review"})
        if path.endswith("/notification-complete"):
            return FakeResponse({"id": 601, "status": "review"})
        raise AssertionError((method, path, json))

    async def fetch_collection(path):
        return [{
            "id": 601,
            "profile_id": 7,
            "title": "Autonomous topic",
            "body": "A publication-ready post with enough substance.",
            "language": "en",
            "status": "review",
        }]

    async def fetch_profile(profile_id):
        return {"id": profile_id, "name": "Daily Tech", "language": "en", "is_active": True}

    async def send_admin_message(bot, text, admins, reply_markup=None):
        calls.append(("send", admins, reply_markup))
        return True

    monkeypatch.setattr(scheduler, "backend_request", backend_request)
    monkeypatch.setattr(scheduler, "fetch_collection", fetch_collection)
    monkeypatch.setattr(scheduler, "fetch_profile", fetch_profile)
    monkeypatch.setattr(scheduler, "send_admin_message", send_admin_message)
    monkeypatch.setattr(scheduler, "approval_keyboard", lambda content_id, profile_id: ("keyboard", content_id, profile_id))

    await scheduler.retry_pending_notifications(object(), [42])

    assert ("POST", "/content/contents/601/notification-claim", None) in calls
    assert ("POST", "/content/contents/601/notification-complete", None) in calls
    assert calls.index(("send", [42], ("keyboard", 601, 7))) < calls.index(("POST", "/content/contents/601/notification-complete", None))


@pytest.mark.asyncio
async def test_notification_stays_retryable_when_delivery_fails(monkeypatch):
    monkeypatch.setattr(scheduler, "CALLBACK_SECRET", "test-secret")
    completed = []

    async def backend_request(method, path, json=None):
        if path.endswith("/notification-claim"):
            return FakeResponse({"id": 601, "status": "review"})
        if path.endswith("/notification-complete"):
            completed.append(601)
            return FakeResponse({"id": 601, "status": "review"})
        raise AssertionError((method, path, json))

    async def fetch_collection(path):
        return [{
            "id": 601,
            "profile_id": 7,
            "title": "Autonomous topic",
            "body": "A publication-ready post with enough substance.",
            "language": "en",
            "status": "review",
        }]

    async def fetch_profile(profile_id):
        return {"id": profile_id, "name": "Daily Tech", "language": "en", "is_active": True}

    async def send_admin_message(bot, text, admins, reply_markup=None):
        return False

    monkeypatch.setattr(scheduler, "backend_request", backend_request)
    monkeypatch.setattr(scheduler, "fetch_collection", fetch_collection)
    monkeypatch.setattr(scheduler, "fetch_profile", fetch_profile)
    monkeypatch.setattr(scheduler, "send_admin_message", send_admin_message)

    await scheduler.retry_pending_notifications(object(), [42])

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
