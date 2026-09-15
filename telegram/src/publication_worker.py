import asyncio
import logging
import os
import random
import socket
from typing import Any

import httpx
from aiogram import Bot

from providers import PublicationContext, registry

BACKEND_API_URL = os.getenv("BACKEND_API_URL", "http://localhost:8000")
SERVICE_TOKEN = os.getenv("SERVICE_ACCOUNT_TOKEN")
WORKER_ID = os.getenv("PUBLICATION_WORKER_ID") or f"telegram:{socket.gethostname()}"
POLL_INTERVAL_SECONDS = int(os.getenv("PUBLICATION_POLL_INTERVAL_SECONDS", "5"))
MAX_ATTEMPTS = int(os.getenv("PUBLICATION_MAX_ATTEMPTS", "5"))
RETRY_DELAY_SECONDS = int(os.getenv("PUBLICATION_RETRY_DELAY_SECONDS", "60"))
RETRY_MAX_DELAY_SECONDS = int(os.getenv("PUBLICATION_RETRY_MAX_DELAY_SECONDS", "3600"))
RETRY_JITTER_RATIO = float(os.getenv("PUBLICATION_RETRY_JITTER_RATIO", "0.25"))
LEASE_HEARTBEAT_INTERVAL_SECONDS = int(os.getenv("PUBLICATION_LEASE_HEARTBEAT_INTERVAL_SECONDS", "60"))


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
    response = await backend_request("POST", f"/content/publications/{publication_id}/claim", json={"worker_id": WORKER_ID})
    if response.status_code == 409:
        return None
    response.raise_for_status()
    claimed = response.json()
    if not claimed.get("processing_token"):
        raise RuntimeError(f"Publication {publication_id} was claimed without a processing lease")
    return claimed


async def heartbeat_publication(publication_id: int, processing_token: str) -> None:
    response = await backend_request(
        "POST",
        f"/content/publications/{publication_id}/heartbeat",
        json={"worker_id": WORKER_ID, "processing_token": processing_token},
    )
    response.raise_for_status()


async def complete_publication(publication_id: int, external_id: str, processing_token: str) -> None:
    response = await backend_request(
        "POST",
        f"/content/publications/{publication_id}/complete",
        json={"worker_id": WORKER_ID, "processing_token": processing_token, "external_id": external_id},
    )
    response.raise_for_status()


def calculate_retry_delay(attempt_count: int) -> int:
    exponent = max(0, attempt_count - 1)
    base_delay = min(RETRY_MAX_DELAY_SECONDS, RETRY_DELAY_SECONDS * (2**exponent))
    jitter = base_delay * max(0.0, min(RETRY_JITTER_RATIO, 1.0))
    return max(1, min(RETRY_MAX_DELAY_SECONDS, round(base_delay + random.uniform(-jitter, jitter))))


async def fail_publication(publication_id: int, error_message: str, attempt_count: int, processing_token: str) -> None:
    response = await backend_request(
        "POST",
        f"/content/publications/{publication_id}/fail",
        json={
            "worker_id": WORKER_ID,
            "processing_token": processing_token,
            "error_message": error_message[:4000],
            "retry": True,
            "max_attempts": MAX_ATTEMPTS,
            "retry_delay_seconds": calculate_retry_delay(attempt_count),
        },
    )
    response.raise_for_status()


async def recover_stale_publications() -> None:
    response = await backend_request("POST", "/content/publications/recover-stale")
    response.raise_for_status()


async def _lease_heartbeat(publication_id: int, processing_token: str) -> None:
    while True:
        try:
            await heartbeat_publication(publication_id, processing_token)
        except httpx.HTTPStatusError as exc:
            if exc.response.status_code == 409:
                logging.warning("Publication %s lease was lost", publication_id)
            else:
                logging.exception("Failed to renew lease for publication %s", publication_id)
            return
        except Exception:
            logging.exception("Failed to renew lease for publication %s", publication_id)
            return
        await asyncio.sleep(max(1, LEASE_HEARTBEAT_INTERVAL_SECONDS))


async def publish_one(bot: Bot, publication: dict[str, Any]) -> None:
    publication_id = publication["id"]
    claimed = await claim_publication(publication_id)
    if not claimed:
        return

    attempt_count = int(claimed.get("attempt_count") or 1)
    processing_token = claimed["processing_token"]
    heartbeat_task = asyncio.create_task(_lease_heartbeat(publication_id, processing_token))
    try:
        platform = claimed.get("channel_platform", "")
        publisher = registry.get(platform, bot=bot)
        result = await publisher.publish(
            PublicationContext(
                publication_id=publication_id,
                channel_external_id=claimed["channel_external_id"],
                content_body=claimed.get("content_body", ""),
            )
        )
        await complete_publication(publication_id, result.external_id, processing_token)
        logging.info("Publication %s published as %s message(s), first message %s", publication_id, result.message_count, result.external_id)
    except Exception as exc:
        logging.exception("Publication %s failed", publication_id)
        try:
            await fail_publication(publication_id, str(exc), attempt_count, processing_token)
        except httpx.HTTPStatusError as persist_exc:
            if persist_exc.response.status_code == 409:
                logging.warning("Publication %s lease was lost before failure could be persisted", publication_id)
            else:
                logging.exception("Failed to persist failure for publication %s", publication_id)
        except Exception:
            logging.exception("Failed to persist failure for publication %s", publication_id)
    finally:
        heartbeat_task.cancel()
        try:
            await heartbeat_task
        except asyncio.CancelledError:
            pass


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
