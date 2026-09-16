import pytest

from providers.base import AmbiguousPublicationError, ReconciliationResult
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
