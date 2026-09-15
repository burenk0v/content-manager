from aiogram import Bot

from telegram_format import prepare_telegram_chunks
from .base import PublicationContext, PublicationResult


class TelegramPublisher:
    def __init__(self, bot: Bot) -> None:
        self.bot = bot

    async def publish(self, context: PublicationContext) -> PublicationResult:
        chunks = prepare_telegram_chunks(context.content_body)
        if not chunks:
            raise ValueError("Publication content is empty")

        first_message_id: str | None = None
        for chunk in chunks:
            sent = await self.bot.send_message(
                context.channel_external_id,
                chunk,
                parse_mode="HTML",
            )
            if first_message_id is None:
                first_message_id = str(sent.message_id)

        return PublicationResult(
            external_id=first_message_id or "unknown",
            message_count=len(chunks),
        )
