import asyncio
import logging
import os
import re
from html import escape
from typing import Any

import httpx
from aiogram import Bot
from aiogram.types import InlineKeyboardButton, InlineKeyboardMarkup

from openai_client import OpenAIClient

BACKEND_API_URL = os.getenv("BACKEND_API_URL", "http://localhost:8000")
SERVICE_TOKEN = os.getenv("SERVICE_ACCOUNT_TOKEN")
SCHEDULE_CHECK_INTERVAL_SECONDS = int(os.getenv("SCHEDULE_CHECK_INTERVAL_SECONDS", "10"))


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


async def fetch_ready_profiles() -> list[dict[str, Any]]:
    return await fetch_collection("/content/profiles/ready")


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


async def claim_profile_run(profile_id: int, *, force: bool = False) -> dict[str, Any]:
    path = f"/content/profiles/{profile_id}/claim"
    if force:
        path += "?force=true&record_run=false"
    response = await backend_request("POST", path)
    if response.status_code == 409:
        return {}
    response.raise_for_status()
    return response.json()


async def mark_profile_run(profile_id: int) -> dict[str, Any]:
    response = await backend_request("POST", f"/content/profiles/{profile_id}/run")
    response.raise_for_status()
    return response.json()


async def fetch_contents(workspace_id: int) -> list[dict[str, Any]]:
    return await fetch_collection(f"/content/contents?workspace_id={workspace_id}")


async def create_content(profile: dict[str, Any], topic_name: str, generated_text: str) -> dict[str, Any]:
    response = await backend_request(
        "POST",
        "/content/contents",
        json={
            "workspace_id": profile["workspace_id"],
            "profile_id": profile["id"],
            "title": topic_name,
            "body": generated_text,
            "language": profile["language"],
            "source": "ai",
        },
    )
    response.raise_for_status()
    return response.json()


async def transition_content(content_id: int, status: str) -> dict[str, Any]:
    response = await backend_request(
        "POST",
        f"/content/contents/{content_id}/transition",
        json={"status": status},
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


async def complete_notification(content_id: int) -> None:
    response = await backend_request("POST", f"/content/contents/{content_id}/notification-complete")
    response.raise_for_status()


def build_generation_prompt(profile: dict[str, Any], used_names: set[str]) -> str:
    settings = [
        f"Channel: {profile.get('channel_name') or profile.get('channel_external_id') or 'Telegram channel'}",
        f"Language: {profile.get('language') or 'en'}",
        f"Topic/niche: {profile.get('topic_niche') or 'Choose a useful, timely topic in the channel niche'}",
        f"Tone: {profile.get('tone') or 'Clear, useful, and natural'}",
        f"Content format: {profile.get('content_format') or 'Publication-ready Telegram post'}",
        f"Editorial rules: {profile.get('rules') or 'No clickbait; no placeholders; provide useful substance'}",
    ]
    existing_topics = ", ".join(sorted(used_names)) if used_names else "none"
    return (
        "You are an autonomous content editor. You own topic ideation and must choose the topic yourself. "
        "Do not ask the operator for a topic. Avoid previously used topics. Write a complete publication-ready post. "
        "Never output scripts, styles, placeholders, or an outline. Return exactly:\n"
        "TOPIC: <short topic name>\n"
        "POST: <ready-to-publish message>\n\n"
        "Content profile:\n- " + "\n- ".join(settings) +
        "\n\nPreviously used topics (avoid these): " + existing_topics
    )


async def generate_and_send_profile(bot: Bot, ai_client: OpenAIClient, profile: dict[str, Any], admins: list[int], *, force: bool = False) -> bool:
    try:
        profile = await claim_profile_run(profile["id"], force=force)
    except Exception:
        logging.exception("Failed to claim profile %s", profile["id"])
        return False
    if not profile:
        return False
    contents = await fetch_contents(profile["workspace_id"])
    used_names = {str(item.get("title") or "").strip().lower() for item in contents if item.get("title")}

    for attempt in range(3):
        generated = ai_client.chat(
            build_generation_prompt(profile, used_names),
            system_message="You are an autonomous content editor. Produce complete publication-ready content.",
        )
        parsed = parse_generation_output(generated)
        if not parsed:
            logging.warning("Profile %s generation attempt %s was unparsable", profile["id"], attempt + 1)
            continue
        topic_name, generated_text = parsed
        if not validate_generated_content(topic_name, generated_text, used_names):
            logging.warning("Profile %s generation attempt %s failed validation", profile["id"], attempt + 1)
            continue
        generated_text = prepare_telegram_content(generated_text)
        if not validate_generated_content(topic_name, generated_text, used_names):
            continue

        content = await create_content(profile, topic_name, generated_text)
        await transition_content(content["id"], "review")

        keyboard = InlineKeyboardMarkup(inline_keyboard=[
            [
                InlineKeyboardButton(text="Approve", callback_data=f"approve:{content['id']}:{profile['id']}"),
                InlineKeyboardButton(text="Reject", callback_data=f"reject:{content['id']}"),
            ],
            [InlineKeyboardButton(text="Regenerate", callback_data=f"regenerate:{profile['id']}:{content['id']}")],
        ])
        payload = (
            f"<b>Profile:</b> {escape(str(profile['name']))}\n"
            f"<b>Topic:</b> {escape(topic_name)}\n"
            f"<b>Language:</b> {escape(profile['language'])}\n\n{generated_text}"
        )
        if await send_admin_message(bot, payload, admins, keyboard):
            await complete_notification(content["id"])
            return True
        logging.error("Approval notification delivery failed for content %s; it remains retryable", content["id"])
        return False

    await request_profile_regeneration(profile["id"])
    await send_admin_message(bot, f"⚠️ Не удалось подготовить валидный пост для профиля {profile['name']} после 3 попыток. Профиль оставлен в очереди на повтор.", admins)
    return False


async def retry_pending_notifications(bot: Bot, admins: list[int]) -> None:
    contents = await fetch_collection("/content/contents")
    for item in contents:
        if item.get("status") != "review" or item.get("approval_notification_sent_at") is not None or not item.get("profile_id"):
            continue
        claimed = await claim_notification(int(item["id"]))
        if not claimed:
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
        keyboard = InlineKeyboardMarkup(inline_keyboard=[
            [
                InlineKeyboardButton(text="Approve", callback_data=f"approve:{item['id']}:{profile['id']}"),
                InlineKeyboardButton(text="Reject", callback_data=f"reject:{item['id']}"),
            ],
            [InlineKeyboardButton(text="Regenerate", callback_data=f"regenerate:{profile['id']}:{item['id']}")],
        ])
        if await send_admin_message(bot, payload, admins, keyboard):
            await complete_notification(int(item["id"]))


async def schedule_worker(bot: Bot, ai_client: OpenAIClient, admins: list[int]) -> None:
    while True:
        try:
            await retry_pending_notifications(bot, admins)
            profiles = await fetch_ready_profiles()
            for profile in profiles:
                await generate_and_send_profile(bot, ai_client, profile, admins)
        except Exception:
            logging.exception("Error while processing autonomous content profiles")
        await asyncio.sleep(SCHEDULE_CHECK_INTERVAL_SECONDS)
