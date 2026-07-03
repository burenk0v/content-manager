import asyncio
import os
from aiogram import Bot, Dispatcher, types
from aiogram.filters import Command
from aiogram.types import InlineKeyboardButton, InlineKeyboardMarkup

BOT_TOKEN = os.getenv("BOT_TOKEN")  # Токен бота из переменных окружения
WEBAPP_URL = os.getenv("WEBAPP_URL")  # URL вашего WebApp

async def main():
    # Инициализация бота и диспетчера
    bot = Bot(token=BOT_TOKEN)
    dp = Dispatcher()

    @dp.message(Command(commands=['start']))
    async def start_command(message: types.Message):
        # Создаем кнопку для открытия WebApp
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

    # Запуск поллинга
    await dp.start_polling(bot)

if __name__ == "__main__":
    asyncio.run(main())