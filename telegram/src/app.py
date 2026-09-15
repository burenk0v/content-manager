import asyncio
import contextlib
import logging
import os
import re
from html import escape
from urllib.parse import urlparse

from aiogram import Bot, Dispatcher, types
from aiogram.filters import Command
from aiogram.types import InlineKeyboardButton, InlineKeyboardMarkup

from openai_client import OpenAIClient
from publication_worker import publication_worker
from scheduler import delete_draft, fetch_draft, fetch_schedule, generate_and_send_draft, schedule_worker

BOT_TOKEN = os.getenv("BOT_TOKEN")
ADMINS = [int(x) for x in os.getenv("ADMINS", "").split(",") if x.strip()]


def prepare_telegram_content(text: str) -> str:
    text = (text or "").strip()
    if not text:
        return text

    if re.search(r"</?[a-zA-Z][^>]*>", text):
        allowed = {"b", "i", "u", "code", "pre", "a"}
        stack: list[str] = []

        def replace(match: re.Match[str]) -> str:
            raw, tag, attrs = match.group(0), match.group(1).lower(), match.group(2) or ""
            if raw.startswith("</"):
                if tag in allowed and stack and stack[-1] == tag:
                    stack.pop()
                    return f"</{tag}>"
                return ""
            if tag not in allowed:
                return ""
            if tag == "a":
                href = re.search(r'href=["\']([^"\']+)["\']', attrs, re.I)
                if not href or not href.group(1).startswith(("http://", "https://")):
                    return ""
                stack.append(tag)
                return f'<a href="{escape(href.group(1), quote=True)}">'
            stack.append(tag)
            return f"<{tag}>"

        result = re.sub(r"</?([a-zA-Z0-9]+)([^>]*)>", replace, text)
        while stack:
            result += f"</{stack.pop()}>"
        return result

    lines = []
    in_code = False
    code_lines: list[str] = []
    for line in text.splitlines():
        if line.strip().startswith("```"):
            if in_code:
                lines.append(f"<pre><code>{escape(chr(10).join(code_lines))}</code></pre>")
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
        if rendered.startswith("- "):
            rendered = "• " + rendered[2:]
        lines.append(rendered)
    if in_code:
        lines.append(f"<pre><code>{escape(chr(10).join(code_lines))}</code></pre>")
    return "\n".join(lines)


def is_admin(user_id: int) -> bool:
    return user_id in ADMINS


def webapp_url() -> str | None:
    raw = (os.getenv("WEBAPP_URL") or "").strip()
    if not raw:
        return None
    parsed = urlparse(raw)
    if parsed.scheme != "https" or not parsed.netloc or "." not in (parsed.hostname or ""):
        return None
    return raw


async def main() -> None:
    bot = Bot(token=BOT_TOKEN)
    dp = Dispatcher()
    ai_client = OpenAIClient()

    @dp.message(Command(commands=["start"]))
    async def start(message: types.Message):
        if not is_admin(message.from_user.id):
            await message.answer("Access is allowed only for administrators.")
            return
        url = webapp_url()
        if not url:
            await message.answer("WebApp is currently unavailable.")
            return
        await message.answer("Click the button below to open the WebApp:", reply_markup=InlineKeyboardMarkup(inline_keyboard=[[InlineKeyboardButton(text="Открыть WebApp", web_app=types.WebAppInfo(url=url))]]))

    @dp.message()
    async def messages(message: types.Message):
        if not is_admin(message.from_user.id):
            return
        text = (message.text or "").strip()
        if text.startswith("/ask"):
            prompt = text[4:].strip()
            if not prompt:
                await message.answer("Please provide a request after the /ask command")
                return
            result = prepare_telegram_content(ai_client.chat(prompt))
            await message.answer(result, parse_mode="HTML")

    @dp.callback_query()
    async def callbacks(callback: types.CallbackQuery):
        if not is_admin(callback.from_user.id):
            await callback.answer("Access denied.", show_alert=True)
            return
        data = callback.data or ""

        if data.startswith("approve:"):
            draft_id = int(data.split(":", 1)[1])
            draft = await fetch_draft(draft_id)
            if not draft or draft.get("status") != "pending":
                await callback.answer("Draft not found or already processed.", show_alert=True)
                return
            schedule = await fetch_schedule(draft["schedule_id"])
            if not schedule:
                await callback.answer("Schedule not found.", show_alert=True)
                return
            try:
                from scheduler import create_publication_from_draft
                publication = await create_publication_from_draft(draft_id)
                await callback.answer("Post scheduled for publication.")
                await bot.send_message(callback.from_user.id, f"Publication #{publication['id']} queued for {schedule['name']}.")
                try:
                    await bot.delete_message(callback.message.chat.id, callback.message.message_id)
                except Exception:
                    pass
            except Exception:
                logging.exception("Failed to queue draft %s", draft_id)
                await callback.answer("Failed to schedule post.", show_alert=True)

        elif data.startswith("reject:"):
            draft_id = int(data.split(":", 1)[1])
            draft = await fetch_draft(draft_id)
            if not draft or draft.get("status") != "pending":
                await callback.answer("Draft not found or already processed.", show_alert=True)
                return
            try:
                from scheduler import update_draft_status
                await update_draft_status(draft_id, "rejected")
                await callback.answer("Draft rejected.")
            finally:
                try:
                    await bot.delete_message(callback.message.chat.id, callback.message.message_id)
                except Exception:
                    pass

        elif data.startswith("delete:"):
            draft_id = int(data.split(":", 1)[1])
            try:
                await delete_draft(draft_id)
                await callback.answer("Draft deleted.")
            except Exception:
                await callback.answer("Failed to delete draft.", show_alert=True)
            finally:
                try:
                    await bot.delete_message(callback.message.chat.id, callback.message.message_id)
                except Exception:
                    pass

        elif data.startswith("regenerate:"):
            schedule_id = int(data.split(":", 1)[1])
            schedule = await fetch_schedule(schedule_id)
            if not schedule or not schedule.get("is_active", False):
                await callback.answer("Schedule is unavailable.", show_alert=True)
                return
            await callback.answer("Regenerating draft...")
            if not await generate_and_send_draft(bot, ai_client, schedule, ADMINS):
                await bot.send_message(callback.from_user.id, f"Не удалось перегенерировать расписание {schedule['name']}.")
        else:
            await callback.answer()

    schedule_task = asyncio.create_task(schedule_worker(bot, ai_client, ADMINS))
    publication_task = asyncio.create_task(publication_worker(bot))
    try:
        await dp.start_polling(bot)
    finally:
        for task in (schedule_task, publication_task):
            task.cancel()
        for task in (schedule_task, publication_task):
            with contextlib.suppress(asyncio.CancelledError):
                await task


if __name__ == "__main__":
    asyncio.run(main())
