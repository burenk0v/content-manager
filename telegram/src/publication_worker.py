import asyncio
import logging
import os
import socket
from typing import Any

import httpx
from aiogram import Bot

BACKEND_API_URL = os.getenv("BACKEND_API_URL", "http://localhost:8000")
SERVICE_TOKEN = os.getenv("SERVICE_ACCOUNT_TOKEN")
WORKER_ID = os.getenv("PUBLICATION_WORKER_ID") or f"telegram:{socket.gethostname()}"
POLL_INTERVAL_SECONDS = int(os.getenv("PUBLICATION_POLL_INTERVAL_SECONDS", "5"))
MAX_ATTEMPTS = int(os.getenv("PUBLICATION_MAX_ATTEMPTS", "5"))
RETRY_DELAY_SECONDS = int(os.getenv("PUBLICATION_RETRY_DELAY_SECONDS", "60"))


def backend_url(path: str) -> str:
    return f"{BACKEND_API_URL.rstrip('/')}{path}"


async def backend_request(method: str, path: str, json: Any | None = None) -> httpx.Response:
    headers = {"X-Service-Token": SERVICE_TOKEN} if SERVICE_TOKEN else {}
    async with httpx.AsyncClient(timeout=30) as client:
        return await client.request(method, backend_url(path), json=json, headers=headers)


async def fetch_ready_publications() -> list[dict[str, Any]]:
    response = await backend_request("GET", "/content/publications/ready?limit=20")
    response.raise_for_status()
    return response.json()


async def claim_publication(publication_id: int) -> dict[str, Any] | None:
    response = await backend_request(
        "POST",
        f"/content/publications/{publication_id}/claim",
        json={"worker_id": WORKER_ID},
    )
    if response.status_code == 409:
        return None
    response.raise_for_status()
    return response.json()


async def complete_publication(publication_id: int, external_id: str) -> None:
    response = await backend_request(
        "POST",
        f"/content/publications/{publication_id}/complete",
        json={"worker_id": WORKER_ID, "external_id": external_id},
    )
    response.raise_for_status()


async def fail_publication(publication_id: int, error_message: str) -> None:
    response = await backend_request(
        "POST",
        f"/content/publications/{publication_id}/fail",
        json={
            "worker_id": WORKER_ID,
            "error_message": error_message[:4000],
            "retry": True,
            "max_attempts": MAX_ATTEMPTS,
            "retry_delay_seconds": RETRY_DELAY_SECONDS,
        },
    )
    response.raise_for_status()


async def recover_stale_publications() -> None:
    response = await backend_request("POST", "/content/publications/recover-stale")
    response.raise_for_status()


async def publish_one(bot: Bot, publication: dict[str, Any]) -> None:
    publication_id = publication["id"]
    claimed = await claim_publication(publication_id)
    if not claimed:
        return

    try:
        if claimed.get("channel_platform") not in {None, "telegram"}:
            raise RuntimeError(f"Unsupported publication platform: {claimed.get('channel_platform')}")

        sent = await bot.send_message(
            claimed["channel_external_id"],
            claimed["content_body"],
            parse_mode="HTML",
        )
        await complete_publication(publication_id, str(sent.message_id))
        logging.info("Publication %s published as Telegram message %s", publication_id, sent.message_id)
    except Exception as exc:
        logging.exception("Publication %s failed", publication_id)
        try:
            await fail_publication(publication_id, str(exc))
        except Exception:
            logging.exception("Failed to persist failure for publication %s", publication_id)


async def publication_worker(bot: Bot) -> None:
    while True:
        try:
            await recover_stale_publications()
            publications = await fetch_ready_publications()
            for publication in publications:
                await publish_one(bot, publication)
        except Exception:
            logging.exception("Error while processing publication queue")
        await asyncio.sleep(POLL_INTERVAL_SECONDS)
