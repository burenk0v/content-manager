import asyncio
import logging
import os
import re
from datetime import datetime
from html import escape
from typing import Any

import httpx
from aiogram import Bot
from aiogram.types import InlineKeyboardButton, InlineKeyboardMarkup

from openai_client import OpenAIClient

BACKEND_API_URL = os.getenv("BACKEND_API_URL", "http://localhost:8000")
SERVICE_TOKEN = os.getenv("SERVICE_ACCOUNT_TOKEN")


def get_schedule_check_interval_seconds() -> int:
    raw_seconds = os.getenv("SCHEDULE_CHECK_INTERVAL_SECONDS")
    if raw_seconds is not None:
        return int(raw_seconds)

    raw_minutes = os.getenv("SCHEDULE_CHECK_INTERVAL_MINUTES")
    if raw_minutes is not None:
        return int(raw_minutes) * 60

    return 10


SCHEDULE_CHECK_INTERVAL_SECONDS = get_schedule_check_interval_seconds()


def get_backend_url(path: str) -> str:
    return f"{BACKEND_API_URL.rstrip('/')}{path}"


async def backend_request(method: str, path: str, json: Any | None = None) -> httpx.Response:
    headers = {}
    if SERVICE_TOKEN:
        headers["X-Service-Token"] = SERVICE_TOKEN
    async with httpx.AsyncClient(timeout=30) as client:
        return await client.request(method, get_backend_url(path), json=json, headers=headers)


async def fetch_topics() -> list[dict[str, Any]]:
    response = await backend_request("GET", "/content/topics")
    response.raise_for_status()
    return response.json()


async def fetch_ready_schedules() -> list[dict[str, Any]]:
    response = await backend_request("GET", "/content/schedules/ready")
    response.raise_for_status()
    return response.json()


async def fetch_schedule(schedule_id: int) -> dict[str, Any] | None:
    response = await backend_request("GET", f"/content/schedules/{schedule_id}")
    if response.status_code == 404:
        return None
    response.raise_for_status()
    return response.json()


async def fetch_draft(draft_id: int) -> dict[str, Any] | None:
    response = await backend_request("GET", f"/content/drafts/{draft_id}")
    if response.status_code == 404:
        return None
    response.raise_for_status()
    return response.json()


async def update_draft_status(draft_id: int, status: str) -> dict[str, Any]:
    response = await backend_request("PATCH", f"/content/drafts/{draft_id}", json={"status": status})
    response.raise_for_status()
    return response.json()


async def delete_draft(draft_id: int) -> None:
    response = await backend_request("DELETE", f"/content/drafts/{draft_id}")
    response.raise_for_status()


async def update_schedule_last_run(schedule_id: int, last_run: datetime) -> None:
    response = await backend_request(
        "PUT",
        f"/content/schedules/{schedule_id}",
        json={"last_run": last_run.isoformat(), "force_run_requested_at": None},
    )
    try:
        response.raise_for_status()
    except Exception as exc:
        logging.exception("Failed to update last_run for schedule %s: %s", schedule_id, exc)
        raise


async def create_draft(
    schedule_id: int,
    topic_name: str,
    language: str,
    generated_text: str,
) -> dict[str, Any]:
    response = await backend_request(
        "POST",
        "/content/drafts",
        json={
            "schedule_id": schedule_id,
            "topic_name": topic_name,
            "language": language,
            "generated_text": generated_text,
            "status": "pending",
        },
    )
    response.raise_for_status()
    return response.json()


def normalize_topic_name(text: str) -> str:
    return text.strip().strip('"').strip("'")


def parse_generation_output(text: str) -> tuple[str, str] | None:
    if not text:
        return None
    text = text.strip()
    patterns = [
        r"TOPIC:\s*(.+?)\s*POST:\s*(.+)",
        r"TOPIC:\s*(.+?)\s*MESSAGE:\s*(.+)",
    ]
    for pattern in patterns:
        match = re.search(pattern, text, re.S | re.I)
        if match:
            topic = normalize_topic_name(match.group(1))
            message = match.group(2).strip()
            return topic, message

    lines = text.splitlines()
    if len(lines) >= 2:
        topic = normalize_topic_name(lines[0])
        message = "\n".join(lines[1:]).strip()
        if topic and message:
            return topic, message

    return None


def validate_generated_content(topic_name: str, generated_text: str, used_names: set[str]) -> bool:
    """Reject obviously unusable AI output before it reaches the approval queue."""
    if not topic_name or not generated_text:
        return False
    if topic_name.lower() in used_names:
        return False
    if len(generated_text.strip()) < 20:
        return False
    if len(generated_text) > 12000:
        return False
    if re.search(r"<\/?(?:script|style|iframe)\b", generated_text, re.I):
        return False
    if re.search(r"\[(?:insert|add|write|replace)|\{\{.*?\}\}", generated_text, re.I):
        return False
    return True


def looks_like_html(text: str) -> bool:
    if not text:
        return False
    return bool(re.search(r"</?[a-zA-Z][^>]*>", text))


def sanitize_telegram_html(text: str) -> str:
    if not text:
        return text

    allowed_tags = {"b", "i", "u", "code", "pre", "a"}
    stack: list[str] = []

    def replace_tag(match: re.Match[str]) -> str:
        raw = match.group(0)
        if raw.startswith("</"):
            tag = match.group(1).lower()
            if tag in allowed_tags and stack and stack[-1] == tag:
                stack.pop()
                return f"</{tag}>"
            return ""

        tag = match.group(1).lower()
        if tag not in allowed_tags:
            return ""

        attrs = match.group(2) or ""
        if tag == "a":
            href_match = re.search(r'href=["\']([^"\']+)["\']', attrs, re.IGNORECASE)
            if not href_match:
                return ""
            href = href_match.group(1)
            if not href.startswith(("http://", "https://")):
                return ""
            stack.append(tag)
            return f'<a href="{escape(href, quote=True)}">'

        stack.append(tag)
        return f"<{tag}>"

    sanitized = re.sub(r"</?([a-zA-Z0-9]+)([^>]*)>", replace_tag, text)
    while stack:
        tag = stack.pop()
        sanitized += f"</{tag}>"
    return sanitized


def prepare_telegram_content(text: str) -> str:
    if not text:
        return text

    text = text.strip()
    if looks_like_html(text):
        return sanitize_telegram_html(text)

    lines = text.splitlines()
    result = []
    in_code_block = False
    code_lines = []

    for line in lines:
        if line.strip().startswith("```"):
            if in_code_block:
                result.append(f"<pre><code>{escape(chr(10).join(code_lines))}</code></pre>")
                code_lines = []
                in_code_block = False
            else:
                in_code_block = True
            continue

        if in_code_block:
            code_lines.append(line)
            continue

        rendered = escape(line)
        rendered = re.sub(r'\*\*(.+?)\*\*', r'<b>\1</b>', rendered)
        rendered = re.sub(r'__(.+?)__', r'<b>\1</b>', rendered)
        rendered = re.sub(r'\*(.+?)\*', r'<i>\1</i>', rendered)
        rendered = re.sub(r'_(.+?)_', r'<i>\1</i>', rendered)
        rendered = re.sub(r'`([^`]+)`', r'<code>\1</code>', rendered)

        if re.match(r'^- ', rendered):
            rendered = "• " + rendered[2:]

        result.append(rendered)

    if in_code_block:
        result.append(f"<pre><code>{escape(chr(10).join(code_lines))}</code></pre>")

    return "\n".join(result)


async def send_admin_message(bot: Bot, text: str, admins: list[int], reply_markup: InlineKeyboardMarkup | None = None) -> bool:
    if not admins:
        logging.warning("No admin IDs configured for Telegram bot; draft delivery skipped.")
        return False

    sent_any = False
    for admin_id in admins:
        try:
            await bot.send_message(admin_id, text, parse_mode="HTML", reply_markup=reply_markup)
            sent_any = True
        except Exception as exc:
            logging.exception("Failed to send admin message to %s: %s", admin_id, exc)

    return sent_any


def build_generation_prompt(schedule: dict[str, Any], used_names: set[str]) -> str:
    existing_topics = ", ".join(sorted(used_names)) if used_names else "none"
    custom_prompt = schedule.get("prompt_text")
    profile = [
        f"Channel: {schedule.get('chat_name') or schedule.get('name') or 'Telegram channel'}",
        f"Language: {schedule.get('language') or 'en'}",
    ]
    if custom_prompt:
        profile.append(f"Editorial brief: {custom_prompt}")

    return (
        "You are an autonomous content editor for a Telegram channel. "
        "You own topic ideation and must choose a useful, timely topic yourself. "
        "Do not ask the operator for a topic. Do not reuse an existing topic. "
        "Write a complete publication-ready post, not an outline or instructions. "
        "Use HTML only when formatting improves readability; never output scripts, styles, or placeholders. "
        "Return exactly two fields:\n"
        "TOPIC: <short topic name>\n"
        "POST: <ready-to-publish message>\n\n"
        "Content profile:\n- " + "\n- ".join(profile) + "\n\n"
        "Previously used topics (avoid these): " + existing_topics
    )


async def generate_and_send_draft(bot: Bot, ai_client: OpenAIClient, schedule: dict[str, Any], admins: list[int]) -> bool:
    current_schedule = await fetch_schedule(schedule["id"])
    if not current_schedule:
        logging.info("Schedule %s was removed before processing", schedule.get("id"))
        return False
    if not current_schedule.get("is_active", False):
        logging.info("Skipping inactive schedule %s", current_schedule.get("id"))
        return False

    schedule = current_schedule
    existing_topics = await fetch_topics()
    used_names = {topic.get("name", "").strip().lower() for topic in existing_topics if topic.get("name")}
    system_message = schedule.get("assistant_template_text") or schedule.get("assistant_message") or (
        "You are an autonomous Telegram content editor. Generate publication-ready content and follow the requested output format."
    )

    for attempt in range(3):
        prompt = build_generation_prompt(schedule, used_names)
        generated = ai_client.chat(prompt, system_message=system_message)
        parsed = parse_generation_output(generated)
        if not parsed:
            logging.warning("AI generation attempt %s returned an unparsable response", attempt + 1)
            continue

        topic_name, generated_text = parsed
        if not validate_generated_content(topic_name, generated_text, used_names):
            logging.warning("AI generation attempt %s failed content validation", attempt + 1)
            continue

        refreshed_schedule = await fetch_schedule(schedule["id"])
        if not refreshed_schedule or not refreshed_schedule.get("is_active", False):
            logging.info("Schedule %s became inactive during generation", schedule.get("id"))
            return False

        schedule = refreshed_schedule
        generated_text = prepare_telegram_content(generated_text)
        if not validate_generated_content(topic_name, generated_text, used_names):
            continue

        draft = await create_draft(
            schedule_id=schedule["id"],
            topic_name=topic_name,
            language=schedule["language"],
            generated_text=generated_text,
        )

        keyboard = InlineKeyboardMarkup(inline_keyboard=[
            [
                InlineKeyboardButton(text="Approve", callback_data=f"approve:{draft['id']}"),
                InlineKeyboardButton(text="Reject", callback_data=f"reject:{draft['id']}"),
            ],
            [
                InlineKeyboardButton(text="Regenerate", callback_data=f"regenerate:{schedule['id']}"),
                InlineKeyboardButton(text="Delete", callback_data=f"delete:{draft['id']}"),
            ],
        ])

        payload_text = (
            f"<b>Schedule:</b> {schedule['name']}\n"
            f"<b>Topic:</b> {topic_name}\n"
            f"<b>Language:</b> {schedule['language']}\n\n"
            f"{generated_text}"
        )
        sent = await send_admin_message(bot, payload_text, admins, keyboard)
        if sent:
            await update_schedule_last_run(schedule["id"], datetime.utcnow())
            return True

        logging.warning("Draft created for schedule %s but admin message failed", schedule["name"])
        return False

    await send_admin_message(
        bot,
        f"⚠️ Не удалось подготовить валидный пост для расписания {schedule['name']} после 3 попыток. Проверьте настройки контент-профиля.",
        admins,
    )
    return False


async def schedule_worker(bot: Bot, ai_client: OpenAIClient, admins: list[int]) -> None:
    while True:
        try:
            schedules = await fetch_ready_schedules()
            if not schedules:
                logging.debug("No ready schedules found.")
            for schedule in schedules:
                await generate_and_send_draft(bot, ai_client, schedule, admins)
        except Exception:
            logging.exception("Error while processing scheduled drafts")
        await asyncio.sleep(SCHEDULE_CHECK_INTERVAL_SECONDS)
