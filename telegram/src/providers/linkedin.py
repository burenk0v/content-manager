import os

import httpx

from .base import (
    AmbiguousPublicationError,
    PermanentPublicationError,
    ProviderCapabilities,
    PublicationContext,
    PublicationResult,
)


LINKEDIN_API_URL = os.getenv("LINKEDIN_API_URL", "https://api.linkedin.com/rest")
LINKEDIN_VERSION = os.getenv("LINKEDIN_VERSION", "202609")
LINKEDIN_ACCESS_TOKEN = os.getenv("LINKEDIN_ACCESS_TOKEN")


class LinkedInPublisher:
    """Publish text-only posts to an authenticated member's LinkedIn profile."""

    capabilities = ProviderCapabilities(
        supports_idempotency=False,
        supports_reconciliation=False,
    )

    def __init__(
        self,
        access_token: str | None = None,
        *,
        api_url: str = LINKEDIN_API_URL,
        version: str = LINKEDIN_VERSION,
    ) -> None:
        self.access_token = access_token or os.getenv("LINKEDIN_ACCESS_TOKEN")
        self.api_url = api_url.rstrip("/")
        self.version = version
        if not self.access_token:
            raise PermanentPublicationError("LINKEDIN_ACCESS_TOKEN is not configured")

    async def publish(self, context: PublicationContext) -> PublicationResult:
        author = context.channel_external_id.strip()
        if not author.startswith("urn:li:person:"):
            raise PermanentPublicationError(
                "LinkedIn channel external_id must be a member URN (urn:li:person:...)"
            )
        if not context.content_body.strip():
            raise PermanentPublicationError("Publication content is empty")
        if not self.version.isdigit() or len(self.version) != 6:
            raise PermanentPublicationError("LINKEDIN_VERSION must use YYYYMM format")

        payload = {
            "author": author,
            "commentary": context.content_body,
            "visibility": "PUBLIC",
            "distribution": {
                "feedDistribution": "MAIN_FEED",
                "targetEntities": [],
                "thirdPartyDistributionChannels": [],
            },
            "lifecycleState": "PUBLISHED",
            "isReshareDisabledByAuthor": False,
        }
        headers = {
            "Authorization": f"Bearer {self.access_token}",
            "Content-Type": "application/json",
            "X-Restli-Protocol-Version": "2.0.0",
            "Linkedin-Version": self.version,
        }

        try:
            async with httpx.AsyncClient(timeout=30) as client:
                response = await client.post(
                    f"{self.api_url}/posts",
                    json=payload,
                    headers=headers,
                )
        except (httpx.TimeoutException, httpx.NetworkError) as exc:
            raise AmbiguousPublicationError(
                f"LinkedIn publication outcome is unknown for key {context.provider_operation_key}"
            ) from exc

        if response.status_code in {401, 403, 400, 422}:
            detail = response.text[:1000]
            raise PermanentPublicationError(
                f"LinkedIn rejected the publication ({response.status_code}): {detail}"
            )
        if response.status_code >= 500:
            raise AmbiguousPublicationError(
                f"LinkedIn returned {response.status_code}; publication outcome is unknown for key "
                f"{context.provider_operation_key}"
            )
        if response.status_code == 429:
            raise RuntimeError("LinkedIn rate limit exceeded")
        if response.status_code < 200 or response.status_code >= 300:
            raise RuntimeError(f"LinkedIn publication failed with HTTP {response.status_code}")

        external_id = response.headers.get("x-restli-id")
        if not external_id:
            raise AmbiguousPublicationError(
                f"LinkedIn accepted the request without returning x-restli-id for key "
                f"{context.provider_operation_key}"
            )

        return PublicationResult(external_id=external_id, message_count=1)
