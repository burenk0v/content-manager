import os
from typing import Any

import httpx

BACKEND_API_URL = os.getenv("BACKEND_API_URL", "http://localhost:8000")
SERVICE_TOKEN = os.getenv("SERVICE_ACCOUNT_TOKEN")


async def create_publication_from_draft(draft_id: int) -> dict[str, Any]:
    headers = {"X-Service-Token": SERVICE_TOKEN} if SERVICE_TOKEN else {}
    url = f"{BACKEND_API_URL.rstrip('/')}/content/publications/from-draft/{draft_id}"
    async with httpx.AsyncClient(timeout=30) as client:
        response = await client.post(url, headers=headers)
    response.raise_for_status()
    return response.json()
