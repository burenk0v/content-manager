import pytest

from providers.base import AmbiguousPublicationError, PermanentPublicationError, ReconciliationResult
from src.publication_worker import publish_one, reconcile_unknown_publication


class FakeBot:
    def __init__(self):
        self.calls = []

    async def send_message(self, chat_id, text, parse_mode=None):
        self.calls.append((chat_id, text, parse_mode))
        return type("Message", (), {"message_id": 42 + len(self.calls) - 1})()


@pytest.fixture(autouse=True)
def disable_heartbeat(monkeypatch):
    async def heartbeat(publication_id, processing_token):
        return None

    monkeypatch.setattr("src.publication_worker.heartbeat_publication", heartbeat)


@pytest.mark.asyncio
async def test_publish_one_uses_telegram_adapter(monkeypatch):
    bot = FakeBot()
    completed = []

    async def claim(publication_id):
        return {"id": 7, "channel_platform": "telegram", "channel_external_id": "@channel", "content_body": "<b>Hello</b>", "provider_operation_key": "publication:provider-7", "attempt_count": 1, "processing_token": "token-7"}

    async def complete(publication_id, external_id, processing_token):
        completed.append((publication_id, external_id, processing_token))

    monkeypatch.setattr("src.publication_worker.claim_publication", claim)
    monkeypatch.setattr("src.publication_worker.complete_publication", complete)
    await publish_one(bot, {"id": 7})
    assert bot.calls == [("@channel", "<b>Hello</b>", "HTML")]
    assert completed == [(7, "42", "token-7")]


@pytest.mark.asyncio
async def test_publish_one_splits_oversized_content(monkeypatch):
    bot = FakeBot()
    completed = []

    async def claim(publication_id):
        return {"id": 8, "channel_platform": "telegram", "channel_external_id": "@channel", "content_body": "x" * 8000, "provider_operation_key": "publication:provider-8", "attempt_count": 1, "processing_token": "token-8"}

    async def complete(publication_id, external_id, processing_token):
        completed.append((publication_id, external_id, processing_token))

    monkeypatch.setattr("src.publication_worker.claim_publication", claim)
    monkeypatch.setattr("src.publication_worker.complete_publication", complete)
    await publish_one(bot, {"id": 8})
    assert len(bot.calls) == 3
    assert all(call[0] == "@channel" and call[2] == "HTML" for call in bot.calls)
    assert all(len(call[1]) <= 3800 for call in bot.calls)
    assert completed == [(8, "42", "token-8")]


@pytest.mark.asyncio
async def test_publish_one_rejects_unsupported_platform_without_retry(monkeypatch):
    bot = FakeBot()
    failures = []

    async def claim(publication_id):
        return {"id": 9, "channel_platform": "instagram", "channel_external_id": "x", "content_body": "Hello", "provider_operation_key": "publication:provider-9", "attempt_count": 1, "processing_token": "token-9"}

    async def fail(publication_id, error_message, processing_token, *, retry):
        failures.append((publication_id, error_message, processing_token, retry))

    monkeypatch.setattr("src.publication_worker.claim_publication", claim)
    monkeypatch.setattr("src.publication_worker.fail_publication", fail)
    await publish_one(bot, {"id": 9})
    assert failures == [(9, "Unsupported publication platform: instagram", "token-9", False)]


@pytest.mark.asyncio
async def test_publish_one_does_not_send_when_claim_is_lost(monkeypatch):
    bot = FakeBot()

    async def claim(publication_id):
        return None

    monkeypatch.setattr("src.publication_worker.claim_publication", claim)
    await publish_one(bot, {"id": 7})
    assert bot.calls == []


@pytest.mark.asyncio
async def test_publish_one_persists_send_failure_with_retry(monkeypatch):
    bot = FakeBot()
    failures = []

    async def claim(publication_id):
        return {"id": 7, "channel_platform": "telegram", "channel_external_id": "@channel", "content_body": "Hello", "provider_operation_key": "publication:provider-7", "attempt_count": 2, "processing_token": "token-7"}

    async def fail(publication_id, error_message, processing_token, *, retry):
        failures.append((publication_id, error_message, processing_token, retry))

    async def send_message(*args, **kwargs):
        raise RuntimeError("Telegram unavailable")

    bot.send_message = send_message
    monkeypatch.setattr("src.publication_worker.claim_publication", claim)
    monkeypatch.setattr("src.publication_worker.fail_publication", fail)
    await publish_one(bot, {"id": 7})
    assert failures == [(7, "Telegram unavailable", "token-7", True)]


@pytest.mark.asyncio
async def test_publish_one_persists_permanent_failure_without_retry(monkeypatch):
    bot = FakeBot()
    failures = []

    class PermanentPublisher:
        async def publish(self, context):
            raise PermanentPublicationError("chat was blocked")

    async def claim(publication_id):
        return {"id": 13, "channel_platform": "telegram", "channel_external_id": "@channel", "content_body": "Hello", "provider_operation_key": "publication:provider-13", "attempt_count": 1, "processing_token": "token-13"}

    async def fail(publication_id, error_message, processing_token, *, retry):
        failures.append((publication_id, error_message, processing_token, retry))

    monkeypatch.setattr("src.publication_worker.claim_publication", claim)
    monkeypatch.setattr("src.publication_worker.fail_publication", fail)
    monkeypatch.setattr("src.publication_worker.registry.get", lambda platform, **kwargs: PermanentPublisher())
    await publish_one(bot, {"id": 13})
    assert failures == [(13, "chat was blocked", "token-13", False)]


@pytest.mark.asyncio
async def test_publish_one_does_not_retry_ambiguous_provider_outcome(monkeypatch):
    bot = FakeBot()
    failures = []

    class AmbiguousPublisher:
        async def publish(self, context):
            assert context.provider_operation_key == "publication:provider-10"
            raise AmbiguousPublicationError("provider outcome unknown")

    async def claim(publication_id):
        return {"id": 10, "channel_platform": "telegram", "channel_external_id": "@channel", "content_body": "Hello", "provider_operation_key": "publication:provider-10", "attempt_count": 1, "processing_token": "token-10"}

    async def fail(publication_id, error_message, processing_token, *, retry):
        failures.append((publication_id, error_message, processing_token, retry))

    monkeypatch.setattr("src.publication_worker.claim_publication", claim)
    monkeypatch.setattr("src.publication_worker.fail_publication", fail)
    monkeypatch.setattr("src.publication_worker.registry.get", lambda platform, **kwargs: AmbiguousPublisher())
    await publish_one(bot, {"id": 10})
    assert failures == [(10, "provider outcome unknown", "token-10", False)]


@pytest.mark.asyncio
async def test_reconcile_unknown_publication_persists_published(monkeypatch):
    calls = []

    class FakeReconciler:
        async def reconcile(self, context):
            assert context.provider_operation_key == "publication:provider-11"
            return ReconciliationResult(outcome="published", external_id="tg-123")

    def get_reconciler(platform, **kwargs):
        return FakeReconciler()

    async def reconcile(publication, result):
        calls.append((publication, result))

    monkeypatch.setattr("src.publication_worker.registry.get_reconciler", get_reconciler)
    monkeypatch.setattr("src.publication_worker.reconcile_publication", reconcile)
    publication = {"id": 11, "channel_platform": "telegram", "channel_external_id": "@channel", "provider_operation_key": "publication:provider-11"}
    await reconcile_unknown_publication(FakeBot(), publication)
    assert calls == [(publication, ReconciliationResult(outcome="published", external_id="tg-123"))]


@pytest.mark.asyncio
async def test_reconcile_unknown_publication_leaves_unknown_when_provider_cannot_decide(monkeypatch):
    calls = []

    class FakeReconciler:
        async def reconcile(self, context):
            return ReconciliationResult(outcome="unknown")

    def get_reconciler(platform, **kwargs):
        return FakeReconciler()

    async def backend_request(method, path, json=None):
        calls.append((method, path, json))
        return type("Response", (), {"raise_for_status": lambda self: None})()

    monkeypatch.setattr("src.publication_worker.registry.get_reconciler", get_reconciler)
    monkeypatch.setattr("src.publication_worker.backend_request", backend_request)
    publication = {"id": 12, "channel_platform": "telegram", "channel_external_id": "@channel", "provider_operation_key": "publication:provider-12"}
    await reconcile_unknown_publication(FakeBot(), publication)
    assert calls == []
