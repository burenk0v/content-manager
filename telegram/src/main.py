import asyncio
import os
from urllib.parse import urlparse

from aiogram import Bot, Dispatcher, types
from aiogram.filters import Command
from aiogram.types import InlineKeyboardButton, InlineKeyboardMarkup



BOT_TOKEN = os.getenv("BOT_TOKEN")  # Токен бота из переменных окружения
ADMINS = [int(x) for x in (os.getenv("ADMINS", "").split(",") if os.getenv("ADMINS") else []) if x.strip()]


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


from openai_client import OpenAIClient


async def main():
    # Инициализация бота и диспетчера
    bot = Bot(token=BOT_TOKEN)
    dp = Dispatcher()
    ai_client = OpenAIClient()

    def is_admin(user_id: int) -> bool:
        if not ADMINS:
            return False
        return user_id in ADMINS

    @dp.message(Command(commands=['start']))
    async def start_command(message: types.Message):
        uid = message.from_user.id
        if not is_admin(uid):
            await message.answer("Доступ разрешён только администраторам.")
            return

        if WEBAPP_URL:
            keyboard = InlineKeyboardMarkup(inline_keyboard=[
                [InlineKeyboardButton(
                    text="Открыть WebApp",
                    web_app=types.WebAppInfo(url=WEBAPP_URL)
                )]
            ])
            await message.answer(
                "Нажмите кнопку ниже, чтобы открыть WebApp:",
                reply_markup=keyboard
            )
        else:
            await message.answer(
                "WebApp пока недоступен. Настройте публичный HTTPS URL в переменной WEBAPP_URL."
            )

    @dp.message()
    async def handle_messages(message: types.Message):
        uid = message.from_user.id
        if not is_admin(uid):
            return  # ignore non-admins

        text = (message.text or "").strip()
        if text.startswith('/ask'):
            # support: /ask <prompt>
            prompt = text[len('/ask'):].strip()
            if not prompt:
                await message.answer("Пожалуйста, укажите запрос после команды /ask")
                return
            await message.answer("Обрабатываю запрос через OpenAI...")
            result = ai_client.chat(prompt)
            await message.answer(result)

    # Запуск поллинга
    await dp.start_polling(bot)


if __name__ == "__main__":
    asyncio.run(main())