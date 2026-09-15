import pytest

from src.publication_worker import calculate_retry_delay, publish_one


class FakeBot:
    def __init__(self):
        self.calls = []

    async def send_message(self, chat_id, text, parse_mode=None):
        self.calls.append((chat_id, text, parse_mode))
        return type("Message", (), {"message_id": 42 + len(self.calls) - 1})()


@pytest.mark.asyncio
async def test_publish_one_uses_telegram_adapter(monkeypatch):
    bot = FakeBot()
    completed = []

    async def claim(publication_id):
        return {"id": 7, "channel_platform": "telegram", "channel_external_id": "@channel", "content_body": "<b>Hello</b>", "attempt_count": 1}

    async def complete(publication_id, external_id):
        completed.append((publication_id, external_id))

    monkeypatch.setattr("src.publication_worker.claim_publication", claim)
    monkeypatch.setattr("src.publication_worker.complete_publication", complete)

    await publish_one(bot, {"id": 7})

    assert bot.calls == [("@channel", "<b>Hello</b>", "HTML")]
    assert completed == [(7, "42")]


@pytest.mark.asyncio
async def test_publish_one_splits_oversized_content(monkeypatch):
    bot = FakeBot()
    completed = []

    async def claim(publication_id):
        return {"id": 8, "channel_platform": "telegram", "channel_external_id": "@channel", "content_body": "x" * 8000, "attempt_count": 1}

    async def complete(publication_id, external_id):
        completed.append((publication_id, external_id))

    monkeypatch.setattr("src.publication_worker.claim_publication", claim)
    monkeypatch.setattr("src.publication_worker.complete_publication", complete)

    await publish_one(bot, {"id": 8})

    assert len(bot.calls) == 3
    assert all(call[0] == "@channel" and call[2] == "HTML" for call in bot.calls)
    assert all(len(call[1]) <= 3800 for call in bot.calls)
    assert completed == [(8, "42")]


@pytest.mark.asyncio
async def test_publish_one_rejects_unsupported_platform(monkeypatch):
    bot = FakeBot()
    failures = []

    async def claim(publication_id):
        return {"id": 9, "channel_platform": "instagram", "channel_external_id": "x", "content_body": "Hello", "attempt_count": 1}

    async def fail(publication_id, error_message, attempt_count):
        failures.append((publication_id, error_message, attempt_count))

    monkeypatch.setattr("src.publication_worker.claim_publication", claim)
    monkeypatch.setattr("src.publication_worker.fail_publication", fail)

    await publish_one(bot, {"id": 9})

    assert failures == [(9, "Unsupported publication platform: instagram", 1)]


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
        return {"id": 7, "channel_platform": "telegram", "channel_external_id": "@channel", "content_body": "Hello", "attempt_count": 2}

    async def fail(publication_id, error_message, attempt_count):
        failures.append((publication_id, error_message, attempt_count))

    async def send_message(*args, **kwargs):
        raise RuntimeError("Telegram unavailable")

    bot.send_message = send_message
    monkeypatch.setattr("src.publication_worker.claim_publication", claim)
    monkeypatch.setattr("src.publication_worker.fail_publication", fail)

    await publish_one(bot, {"id": 7})
    assert failures == [(7, "Telegram unavailable", 2)]


def test_retry_delay_grows_exponentially(monkeypatch):
    monkeypatch.setattr("src.publication_worker.random.uniform", lambda low, high: high)
    assert calculate_retry_delay(1) == 75
    assert calculate_retry_delay(2) == 150
    assert calculate_retry_delay(3) == 300


def test_retry_delay_is_capped(monkeypatch):
    monkeypatch.setattr("src.publication_worker.random.uniform", lambda low, high: high)
    assert calculate_retry_delay(99) == 3600
