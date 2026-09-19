import asyncio
import logging
import hashlib
import hmac
import os
import re
from html import escape
from typing import Any

import httpx
from aiogram import Bot
from aiogram.types import InlineKeyboardButton, InlineKeyboardMarkup


BACKEND_API_URL = os.getenv("BACKEND_API_URL", "http://localhost:8000")
SERVICE_TOKEN = os.getenv("SERVICE_ACCOUNT_TOKEN")
SCHEDULE_CHECK_INTERVAL_SECONDS = int(os.getenv("SCHEDULE_CHECK_INTERVAL_SECONDS", "10"))
CALLBACK_SECRET = os.getenv("TELEGRAM_CALLBACK_SECRET")




def _callback_signature(action: str, *identifiers: int) -> str:
    if not CALLBACK_SECRET:
        raise RuntimeError("TELEGRAM_CALLBACK_SECRET is required")
    payload = ":".join([action, *(str(value) for value in identifiers)])
    return hmac.new(CALLBACK_SECRET.encode(), payload.encode(), hashlib.sha256).hexdigest()[:16]


def build_callback_data(action: str, *identifiers: int) -> str:
    payload = ":".join([action, *(str(value) for value in identifiers)])
    return f"{payload}:{_callback_signature(action, *identifiers)}"


def verify_callback_data(data: str) -> tuple[str, list[int]] | None:
    parts = (data or "").split(":")
    if len(parts) < 3 or not CALLBACK_SECRET:
        return None
    action, *raw_values, signature = parts
    if action not in {"approve", "reject", "regenerate"}:
        return None
    expected_counts = {"approve": 2, "reject": 1, "regenerate": 2}
    if len(raw_values) != expected_counts[action]:
        return None
    try:
        identifiers = [int(value) for value in raw_values]
    except ValueError:
        return None
    if not hmac.compare_digest(signature, _callback_signature(action, *identifiers)):
        return None
    return action, identifiers

def get_backend_url(path: str) -> str:
    return f"{BACKEND_API_URL.rstrip('/')}{path}"


async def backend_request(method: str, path: str, json: Any | None = None) -> httpx.Response:
    headers = {"X-Service-Token": SERVICE_TOKEN} if SERVICE_TOKEN else {}
    async with httpx.AsyncClient(timeout=30) as client:
        return await client.request(method, get_backend_url(path), json=json, headers=headers)


async def fetch_collection(path: str) -> list[dict[str, Any]]:
    response = await backend_request("GET", path)
    response.raise_for_status()
    payload = response.json()
    return payload if isinstance(payload, list) else []


async def fetch_profile(profile_id: int) -> dict[str, Any] | None:
    response = await backend_request("GET", f"/content/profiles/{profile_id}")
    if response.status_code == 404:
        return None
    response.raise_for_status()
    return response.json()


async def request_profile_regeneration(profile_id: int) -> dict[str, Any]:
    response = await backend_request("POST", f"/content/profiles/{profile_id}/regenerate")
    response.raise_for_status()
    return response.json()


async def approve_and_schedule_content(content_id: int, channel_id: int) -> dict[str, Any]:
    response = await backend_request(
        "POST",
        f"/content/contents/{content_id}/approve-and-schedule",
        json={"content_id": content_id, "channel_id": channel_id},
    )
    response.raise_for_status()
    return response.json()


def normalize_topic_name(text: str) -> str:
    return text.strip().strip('"').strip("'")


def parse_generation_output(text: str) -> tuple[str, str] | None:
    if not text:
        return None
    text = text.strip()
    match = re.search(r"TOPIC:\s*(.+?)\s*POST:\s*(.+)", text, re.S | re.I)
    if not match:
        match = re.search(r"TOPIC:\s*(.+?)\s*MESSAGE:\s*(.+)", text, re.S | re.I)
    if match:
        return normalize_topic_name(match.group(1)), match.group(2).strip()
    lines = text.splitlines()
    if len(lines) >= 2:
        topic = normalize_topic_name(lines[0])
        message = "\n".join(lines[1:]).strip()
        if topic and message:
            return topic, message
    return None


def validate_generated_content(topic_name: str, generated_text: str, used_names: set[str]) -> bool:
    if not topic_name or not generated_text or topic_name.lower() in used_names:
        return False
    if len(generated_text.strip()) < 20 or len(generated_text) > 12000:
        return False
    if re.search(r"<\/?(?:script|style|iframe)\b", generated_text, re.I):
        return False
    if re.search(r"\[(?:insert|add|write|replace)|\{\{.*?\}\}", generated_text, re.I):
        return False
    return True


def sanitize_telegram_html(text: str) -> str:
    if not text:
        return text
    allowed_tags = {"b", "i", "u", "code", "pre", "a"}
    stack: list[str] = []

    def replace_tag(match: re.Match[str]) -> str:
        raw = match.group(0)
        tag = match.group(1).lower()
        if raw.startswith("</"):
            if tag in allowed_tags and stack and stack[-1] == tag:
                stack.pop()
                return f"</{tag}>"
            return ""
        if tag not in allowed_tags:
            return ""
        attrs = match.group(2) or ""
        if tag == "a":
            href_match = re.search(r'href=["\']([^"\']+)["\']', attrs, re.I)
            if not href_match or not href_match.group(1).startswith(("http://", "https://")):
                return ""
            stack.append(tag)
            return f'<a href="{escape(href_match.group(1), quote=True)}">'
        stack.append(tag)
        return f"<{tag}>"

    sanitized = re.sub(r"</?([a-zA-Z0-9]+)([^>]*)>", replace_tag, text)
    while stack:
        sanitized += f"</{stack.pop()}>"
    return sanitized


def prepare_telegram_content(text: str) -> str:
    text = (text or "").strip()
    if not text:
        return text
    if re.search(r"</?[a-zA-Z][^>]*>", text):
        return sanitize_telegram_html(text)
    result: list[str] = []
    in_code = False
    code_lines: list[str] = []
    for line in text.splitlines():
        if line.strip().startswith("```"):
            if in_code:
                result.append(f"<pre><code>{escape(chr(10).join(code_lines))}</code></pre>")
                code_lines = []
            in_code = not in_code
            continue
        if in_code:
            code_lines.append(line)
            continue
        rendered = escape(line)
        rendered = re.sub(r'\*\*(.+?)\*\*', r'<b>\1</b>', rendered)
        rendered = re.sub(r'__(.+?)__', r'<b>\1</b>', rendered)
        rendered = re.sub(r'\*(.+?)\*', r'<i>\1</i>', rendered)
        rendered = re.sub(r'_(.+?)_', r'<i>\1</i>', rendered)
        rendered = re.sub(r'`([^`]+)`', r'<code>\1</code>', rendered)
        result.append("• " + rendered[2:] if rendered.startswith("- ") else rendered)
    if in_code:
        result.append(f"<pre><code>{escape(chr(10).join(code_lines))}</code></pre>")
    return "\n".join(result)


async def send_admin_message(bot: Bot, text: str, admins: list[int], reply_markup: InlineKeyboardMarkup | None = None) -> bool:
    if not admins:
        logging.warning("No admin IDs configured for Telegram bot")
        return False
    sent_any = False
    for admin_id in admins:
        for attempt in range(3):
            try:
                await bot.send_message(admin_id, text, parse_mode="HTML", reply_markup=reply_markup)
                sent_any = True
                break
            except Exception:
                logging.exception("Failed to send admin message to %s (attempt %s)", admin_id, attempt + 1)
                if attempt < 2:
                    await asyncio.sleep(1)
    return sent_any


async def claim_notification(content_id: int) -> dict[str, Any] | None:
    response = await backend_request("POST", f"/content/contents/{content_id}/notification-claim")
    if response.status_code == 409:
        return None
    response.raise_for_status()
    return response.json()


async def complete_notification(content_id: int, claim_token: str) -> None:
    response = await backend_request(
        "POST",
        f"/content/contents/{content_id}/notification-complete",
        json={"claim_token": claim_token},
    )
    response.raise_for_status()


def approval_keyboard(content_id: int, profile_id: int) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(inline_keyboard=[
        [
            InlineKeyboardButton(text="Approve", callback_data=build_callback_data("approve", content_id, profile_id)),
            InlineKeyboardButton(text="Reject", callback_data=build_callback_data("reject", content_id)),
        ],
        [InlineKeyboardButton(text="Regenerate", callback_data=build_callback_data("regenerate", profile_id, content_id))],
    ])

async def retry_pending_notifications(bot: Bot, admins: list[int]) -> None:
    contents = await fetch_collection("/content/contents")
    for item in contents:
        if item.get("status") != "review" or item.get("approval_notification_sent_at") is not None or not item.get("profile_id"):
            continue
        claimed = await claim_notification(int(item["id"]))
        if not claimed:
            continue
        claim_token = claimed.get("claim_token")
        if not claim_token:
            logging.error("Notification claim for content %s did not return a claim token", item["id"])
            continue
        profile = await fetch_profile(int(item["profile_id"]))
        if not profile:
            continue
        body = prepare_telegram_content(str(item.get("body") or ""))
        payload = (
            f"<b>Profile:</b> {escape(str(profile['name']))}\n"
            f"<b>Topic:</b> {escape(str(item.get('title') or 'Untitled'))}\n"
            f"<b>Language:</b> {escape(str(item.get('language') or profile.get('language') or 'en'))}\n\n{body}"
        )
        keyboard = approval_keyboard(int(item["id"]), int(profile["id"]))
        if await send_admin_message(bot, payload, admins, keyboard):
            await complete_notification(int(item["id"]), claim_token)


async def notification_worker(bot: Bot, admins: list[int]) -> None:
    """Deliver durable approval notifications; generation belongs to the autonomous scheduler."""
    while True:
        try:
            await retry_pending_notifications(bot, admins)
        except Exception:
            logging.exception("Error while processing Telegram approval notifications")
        await asyncio.sleep(SCHEDULE_CHECK_INTERVAL_SECONDS)
