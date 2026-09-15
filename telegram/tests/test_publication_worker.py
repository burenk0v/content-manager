import pytest

from src.publication_worker import publish_one


class FakeBot:
    def __init__(self):
        self.calls = []

    async def send_message(self, chat_id, text, parse_mode=None):
        self.calls.append((chat_id, text, parse_mode))
        return type("Message", (), {"message_id": 42})()


@pytest.mark.asyncio
async def test_publish_one_claims_sends_and_completes(monkeypatch):
    bot = FakeBot()
    completed = []

    async def claim(publication_id):
        assert publication_id == 7
        return {
            "id": 7,
            "channel_platform": "telegram",
            "channel_external_id": "@channel",
            "content_body": "<b>Hello</b>",
        }

    async def complete(publication_id, external_id):
        completed.append((publication_id, external_id))

    monkeypatch.setattr("src.publication_worker.claim_publication", claim)
    monkeypatch.setattr("src.publication_worker.complete_publication", complete)

    await publish_one(bot, {"id": 7})

    assert bot.calls == [("@channel", "<b>Hello</b>", "HTML")]
    assert completed == [(7, "42")]


@pytest.mark.asyncio
async def test_publish_one_does_not_send_when_claim_is_lost(monkeypatch):
    bot = FakeBot()

    async def claim(publication_id):
        return None

    monkeypatch.setattr("src.publication_worker.claim_publication", claim)

    await publish_one(bot, {"id": 7})

    assert bot.calls == []


@pytest.mark.asyncio
async def test_publish_one_persists_send_failure(monkeypatch):
    bot = FakeBot()
    failures = []

    async def claim(publication_id):
        return {
            "id": 7,
            "channel_platform": "telegram",
            "channel_external_id": "@channel",
            "content_body": "Hello",
        }

    async def fail(publication_id, error_message):
        failures.append((publication_id, error_message))

    async def send_message(*args, **kwargs):
        raise RuntimeError("Telegram unavailable")

    bot.send_message = send_message
    monkeypatch.setattr("src.publication_worker.claim_publication", claim)
    monkeypatch.setattr("src.publication_worker.fail_publication", fail)

    await publish_one(bot, {"id": 7})

    assert failures == [(7, "Telegram unavailable")]
