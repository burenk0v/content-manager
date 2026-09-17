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
from scheduler import (
    backend_request,
    fetch_profile,
    generate_and_send_profile,
    prepare_telegram_content,
    request_profile_regeneration,
    schedule_worker,
    transition_content,
)

BOT_TOKEN = os.getenv("BOT_TOKEN")
ADMINS = [int(x) for x in os.getenv("ADMINS", "").split(",") if x.strip()]


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


async def fetch_collection(path: str) -> list[dict]:
    response = await backend_request("GET", path)
    response.raise_for_status()
    payload = response.json()
    return payload if isinstance(payload, list) else []


async def create_publication(content_id: int, channel_id: int) -> dict:
    response = await backend_request(
        "POST",
        "/content/publications",
        json={"content_id": content_id, "channel_id": channel_id},
    )
    response.raise_for_status()
    return response.json()


async def send_console(message: types.Message, text: str) -> None:
    await message.answer(text, parse_mode="HTML", disable_web_page_preview=True)


async def main() -> None:
    bot = Bot(token=BOT_TOKEN)
    dp = Dispatcher()
    ai_client = OpenAIClient()

    @dp.message(Command(commands=["start", "help"]))
    async def start(message: types.Message):
        if not is_admin(message.from_user.id):
            await message.answer("Access is allowed only for administrators.")
            return
        await send_console(
            message,
            "<b>Content Manager</b>\n\n"
            "AI работает автономно, а Telegram — операционная консоль.\n\n"
            "<b>Команды:</b>\n"
            "/status — состояние системы\n"
            "/queue — публикации на approval\n"
            "/profiles — контент-профили\n"
            "/generate &lt;id&gt; — запустить генерацию профиля сейчас\n"
            "/ask &lt;запрос&gt; — задать AI вопрос\n"
            "/web — открыть настройки",
        )

    @dp.message(Command("web"))
    async def web(message: types.Message):
        if not is_admin(message.from_user.id):
            return
        url = webapp_url()
        if not url:
            await message.answer("WebApp is currently unavailable.")
            return
        await message.answer(
            "Открыть настройки:",
            reply_markup=InlineKeyboardMarkup(
                inline_keyboard=[[InlineKeyboardButton(text="Открыть WebApp", web_app=types.WebAppInfo(url=url))]]
            ),
        )

    @dp.message(Command("status"))
    async def status(message: types.Message):
        if not is_admin(message.from_user.id):
            return
        try:
            profiles = await fetch_collection("/content/profiles")
            contents = await fetch_collection("/content/contents")
            publications = await fetch_collection("/content/publications")
            active = [item for item in profiles if item.get("is_active")]
            review = [item for item in contents if item.get("status") == "review"]
            scheduled = [item for item in publications if item.get("status") == "scheduled"]
            published = [item for item in publications if item.get("status") == "published"]
            await send_console(
                message,
                "<b>System status</b>\n\n"
                f"Profiles: <b>{len(active)}</b> active / {len(profiles)} total\n"
                f"Awaiting approval: <b>{len(review)}</b>\n"
                f"Scheduled publications: <b>{len(scheduled)}</b>\n"
                f"Published: <b>{len(published)}</b>",
            )
        except Exception:
            logging.exception("Failed to build Telegram status")
            await message.answer("Не удалось получить состояние системы.")

    @dp.message(Command("profiles"))
    async def profiles(message: types.Message):
        if not is_admin(message.from_user.id):
            return
        try:
            items = await fetch_collection("/content/profiles")
            if not items:
                await message.answer("Контент-профилей пока нет.")
                return
            lines = ["<b>Content profiles</b>"]
            for item in items:
                state = "🟢" if item.get("is_active") else "⚪️"
                lines.append(f"{state} <b>#{item.get('id')}</b> {escape(str(item.get('name', 'Unnamed')))}")
            await send_console(message, "\n".join(lines))
        except Exception:
            logging.exception("Failed to fetch content profiles")
            await message.answer("Не удалось получить профили.")

    @dp.message(Command("queue"))
    async def queue(message: types.Message):
        if not is_admin(message.from_user.id):
            return
        try:
            contents = [item for item in await fetch_collection("/content/contents") if item.get("status") == "review"]
            if not contents:
                await message.answer("Очередь approval пуста.")
                return
            lines = ["<b>Approval queue</b>"]
            for content in contents[:20]:
                topic = escape(str(content.get("title") or "Без темы"))
                lines.append(f"📝 <b>#{content.get('id')}</b> {topic}")
            await send_console(message, "\n".join(lines))
        except Exception:
            logging.exception("Failed to fetch approval queue")
            await message.answer("Не удалось получить очередь approval.")

    @dp.message(Command("generate"))
    async def generate(message: types.Message):
        if not is_admin(message.from_user.id):
            return
        parts = (message.text or "").split(maxsplit=1)
        if len(parts) != 2 or not parts[1].strip().isdigit():
            await message.answer("Использование: /generate <profile_id>")
            return
        profile_id = int(parts[1].strip())
        profile = await fetch_profile(profile_id)
        if not profile or not profile.get("is_active"):
            await message.answer("Профиль не найден или выключен.")
            return
        await message.answer(f"Запускаю генерацию для <b>{escape(str(profile.get('name', profile_id)))}</b>…", parse_mode="HTML")
        if not await generate_and_send_profile(bot, ai_client, profile, ADMINS, force=True):
            await message.answer("Генерация не удалась. Проверьте настройки профиля и AI.")

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
            await message.answer(prepare_telegram_content(ai_client.chat(prompt)), parse_mode="HTML")

    @dp.callback_query()
    async def callbacks(callback: types.CallbackQuery):
        if not is_admin(callback.from_user.id):
            await callback.answer("Access denied.", show_alert=True)
            return
        data = callback.data or ""
        try:
            if data.startswith("approve:"):
                _, content_id_raw, profile_id_raw = data.split(":", 2)
                content_id = int(content_id_raw)
                profile = await fetch_profile(int(profile_id_raw))
                if not profile:
                    await callback.answer("Профиль не найден.", show_alert=True)
                    return
                await transition_content(content_id, "approved")
                publication = await create_publication(content_id, profile["channel_id"])
                await callback.answer("Post scheduled for publication.")
                await bot.send_message(callback.from_user.id, f"Publication #{publication['id']} queued for {profile['name']}.")
            elif data.startswith("reject:"):
                content_id = int(data.split(":", 1)[1])
                await transition_content(content_id, "draft")
                await callback.answer("Post rejected.")
            elif data.startswith("regenerate:"):
                _, profile_id_raw, content_id_raw = data.split(":", 2)
                profile_id = int(profile_id_raw)
                content_id = int(content_id_raw)
                profile = await fetch_profile(profile_id)
                if not profile or not profile.get("is_active"):
                    await callback.answer("Профиль недоступен.", show_alert=True)
                    return
                await transition_content(content_id, "draft")
                await request_profile_regeneration(profile_id)
                await callback.answer("Regenerating…")
                if not await generate_and_send_profile(bot, ai_client, profile, ADMINS, force=True):
                    await bot.send_message(callback.from_user.id, f"Не удалось перегенерировать профиль {profile['name']}.")
            else:
                await callback.answer()
        except Exception:
            logging.exception("Telegram approval action failed: %s", data)
            await callback.answer("Операция не выполнена. Проверьте состояние записи.", show_alert=True)
        finally:
            with contextlib.suppress(Exception):
                await bot.delete_message(callback.message.chat.id, callback.message.message_id)

    schedule_task = asyncio.create_task(schedule_worker(bot, ai_client, ADMINS))
    publication_task = asyncio.create_task(publication_worker(bot))
    try:
        await dp.start_polling(bot)
    finally:
        schedule_task.cancel()
        publication_task.cancel()
        for task in (schedule_task, publication_task):
            with contextlib.suppress(asyncio.CancelledError):
                await task


if __name__ == "__main__":
    asyncio.run(main())
