import httpx
import pytest

from providers.base import PermanentPublicationError, PublicationContext
from providers.linkedin import LinkedInPublisher


@pytest.fixture
def context() -> PublicationContext:
    return PublicationContext(
        publication_id=7,
        provider_operation_key="publication:test",
        channel_external_id="urn:li:person:abc123",
        content_body="Hello LinkedIn",
    )


class FakeAsyncClient:
    def __init__(self, response: httpx.Response) -> None:
        self.response = response
        self.request: httpx.Request | None = None

    async def __aenter__(self):
        return self

    async def __aexit__(self, exc_type, exc, tb):
        return False

    async def post(self, url, *, json, headers):
        self.request = httpx.Request("POST", url, json=json, headers=headers)
        return self.response


@pytest.mark.asyncio
async def test_publishes_text_post(context, monkeypatch):
    client = FakeAsyncClient(httpx.Response(201, headers={"x-restli-id": "urn:li:share:123"}))
    monkeypatch.setattr("providers.linkedin.httpx.AsyncClient", lambda **kwargs: client)

    publisher = LinkedInPublisher("secret", api_url="https://api.linkedin.test/rest", version="202609")
    result = await publisher.publish(context)

    assert result.external_id == "urn:li:share:123"
    assert result.message_count == 1
    assert client.request is not None
    assert client.request.headers["authorization"] == "Bearer secret"
    assert client.request.headers["linkedin-version"] == "202609"
    assert client.request.headers["x-restli-protocol-version"] == "2.0.0"
    assert client.request.content is not None
    assert b"urn:li:person:abc123" in client.request.content
    assert b"Hello LinkedIn" in client.request.content


@pytest.mark.asyncio
async def test_rejects_non_member_channel(context):
    context = PublicationContext(
        publication_id=context.publication_id,
        provider_operation_key=context.provider_operation_key,
        channel_external_id="urn:li:organization:123",
        content_body=context.content_body,
    )
    publisher = LinkedInPublisher("secret")

    with pytest.raises(PermanentPublicationError, match="member URN"):
        await publisher.publish(context)


@pytest.mark.asyncio
async def test_missing_token_is_permanent_failure(monkeypatch):
    monkeypatch.delenv("LINKEDIN_ACCESS_TOKEN", raising=False)
    with pytest.raises(PermanentPublicationError, match="not configured"):
        LinkedInPublisher()


@pytest.mark.asyncio
async def test_server_error_is_ambiguous(context, monkeypatch):
    client = FakeAsyncClient(httpx.Response(503, text="temporarily unavailable"))
    monkeypatch.setattr("providers.linkedin.httpx.AsyncClient", lambda **kwargs: client)

    publisher = LinkedInPublisher("secret")
    with pytest.raises(Exception, match="outcome is unknown"):
        await publisher.publish(context)
