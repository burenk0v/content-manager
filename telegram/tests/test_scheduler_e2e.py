import pytest

from scheduler import generate_and_send_profile


class FakeBot:
    def __init__(self):
        self.calls = []

    async def send_message(self, chat_id, text, parse_mode=None, reply_markup=None):
        self.calls.append((chat_id, text, parse_mode, reply_markup))
        return object()


class FakeAI:
    def chat(self, *args, **kwargs):
        return "TOPIC: Test topic\nPOST: This is a complete test post with enough content."


@pytest.mark.asyncio
async def test_autonomous_generation_reaches_telegram_review(monkeypatch):
    bot = FakeBot()
    profile = {
        "id": 7,
        "workspace_id": 1,
        "name": "Test profile",
        "language": "en",
        "channel_name": "Test channel",
        "topic_niche": "testing",
        "tone": "clear",
        "content_format": "post",
        "rules": "useful",
    }
    calls = []

    async def claim(profile_id, *, force=False):
        calls.append(("claim", profile_id, force))
        return profile

    async def contents(workspace_id):
        return []

    async def create(profile, topic, body):
        calls.append(("create", topic, body))
        return {"id": 42}

    async def transition(content_id, status):
        calls.append(("transition", content_id, status))
        return {"id": content_id, "status": status}

    async def complete(content_id):
        calls.append(("notification-complete", content_id))

    monkeypatch.setattr("scheduler.claim_profile_run", claim)
    monkeypatch.setattr("scheduler.fetch_contents", contents)
    monkeypatch.setattr("scheduler.create_content", create)
    monkeypatch.setattr("scheduler.transition_content", transition)
    monkeypatch.setattr("scheduler.complete_notification", complete)

    assert await generate_and_send_profile(bot, FakeAI(), profile, [1001])
    assert calls == [
        ("claim", 7, False),
        ("create", "Test topic", "This is a complete test post with enough content."),
        ("transition", 42, "review"),
        ("notification-complete", 42),
    ]
    assert bot.calls and bot.calls[0][0] == 1001
    assert "Test topic" in bot.calls[0][1]
