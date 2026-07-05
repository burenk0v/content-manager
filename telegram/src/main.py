import asyncio
import contextlib
import os
import re
from html import escape
from urllib.parse import urlparse
from typing import Any

from aiogram import Bot, Dispatcher, types
from aiogram.filters import Command
from aiogram.types import InlineKeyboardButton, InlineKeyboardMarkup

from scheduler import fetch_draft, fetch_schedule, generate_and_send_draft, schedule_worker, update_draft_status
from openai_client import OpenAIClient

BOT_TOKEN = os.getenv("BOT_TOKEN")
ADMINS = [int(x) for x in (os.getenv("ADMINS", "").split(",") if os.getenv("ADMINS") else []) if x.strip()]
BACKEND_API_URL = os.getenv("BACKEND_API_URL", "http://localhost:8000")
SERVICE_TOKEN = os.getenv("SERVICE_ACCOUNT_TOKEN")


def get_webapp_url() -> str | None:
    raw_url = (os.getenv("WEBAPP_URL") or "").strip()
    if not raw_url:
        return None

    parsed = urlparse(raw_url)
    if parsed.scheme != "https" or not parsed.netloc:
        return None

    hostname = (parsed.hostname or "").lower()
    if hostname in {"localhost", "127.0.0.1", "0.0.0.0", "frontend", "backend", "host.docker.internal"}:
        return None

    if "." not in hostname:
        return None

    return raw_url


WEBAPP_URL = get_webapp_url()


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
                result.append(f"<pre><code>{escape('\n'.join(code_lines))}</code></pre>")
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
        result.append(f"<pre><code>{escape('\n'.join(code_lines))}</code></pre>")

    return "\n".join(result)


def is_admin(user_id: int) -> bool:
    if not ADMINS:
        return False
    return user_id in ADMINS


async def main():
    bot = Bot(token=BOT_TOKEN)
    dp = Dispatcher()
    ai_client = OpenAIClient()

    @dp.message(Command(commands=['start']))
    async def start_command(message: types.Message):
        uid = message.from_user.id
        if not is_admin(uid):
            await message.answer("Access is allowed only for administrators.")
            return

        if WEBAPP_URL:
            keyboard = InlineKeyboardMarkup(inline_keyboard=[
                [InlineKeyboardButton(
                    text="Открыть WebApp",
                    web_app=types.WebAppInfo(url=WEBAPP_URL)
                )]
            ])
            await message.answer(
                "Click the button below to open the WebApp:",
                reply_markup=keyboard
            )
        else:
            await message.answer(
                "WebApp is currently unavailable. Configure a public HTTPS URL in the WEBAPP_URL environment variable."
            )

    @dp.message()
    async def handle_messages(message: types.Message):
        uid = message.from_user.id
        if not is_admin(uid):
            return

        text = (message.text or "").strip()
        if text.startswith('/ask'):
            prompt = text[len('/ask'):].strip()
            if not prompt:
                await message.answer("Please provide a request after the /ask command")
                return
            await message.answer("Processing your request with OpenAI...")
            result = ai_client.chat(prompt)
            telegram_content = prepare_telegram_content(result)
            await message.answer(telegram_content, parse_mode="HTML")

    @dp.callback_query()
    async def callback_handler(callback: types.CallbackQuery):
        uid = callback.from_user.id
        if not is_admin(uid):
            await callback.answer("Access denied.", show_alert=True)
            return

        data = callback.data or ""
        if data.startswith("publish:"):
            draft_id = int(data.split(":", 1)[1])
            draft = await fetch_draft(draft_id)
            if not draft:
                await callback.answer("Draft not found.", show_alert=True)
                return
            if draft.get("status") != "pending":
                await callback.answer("Draft already processed.", show_alert=True)
                return

            schedule = await fetch_schedule(draft["schedule_id"])
            if not schedule:
                await callback.answer("Schedule not found.", show_alert=True)
                return

            try:
                await bot.send_message(
                    schedule["chat_id"],
                    draft["generated_text"],
                    parse_mode="HTML"
                )
                await update_draft_status(draft_id, "published")
                await callback.answer("Post published.")
            except Exception:
                await callback.answer("Failed to publish post.", show_alert=True)

        elif data.startswith("regenerate:"):
            draft_id = int(data.split(":", 1)[1])
            draft = await fetch_draft(draft_id)
            if not draft:
                await callback.answer("Draft not found.", show_alert=True)
                return
            if draft.get("status") != "pending":
                await callback.answer("Draft already processed.", show_alert=True)
                return

            await update_draft_status(draft_id, "rejected")
            schedule = await fetch_schedule(draft["schedule_id"])
            if not schedule:
                await callback.answer("Schedule not found.", show_alert=True)
                return

            try:
                await bot.delete_message(callback.message.chat.id, callback.message.message_id)
            except Exception:
                pass

            await callback.answer("Regenerating post...")
            await generate_and_send_draft(bot, ai_client, schedule, ADMINS)
        else:
            await callback.answer()

    worker_task = asyncio.create_task(schedule_worker(bot, ai_client, ADMINS))
    try:
        await dp.start_polling(bot)
    finally:
        worker_task.cancel()
        with contextlib.suppress(asyncio.CancelledError):
            await worker_task


if __name__ == "__main__":
    asyncio.run(main())
