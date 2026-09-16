from aiogram import Bot
from aiogram.exceptions import TelegramNetworkError

from telegram_format import prepare_telegram_chunks
from .base import AmbiguousPublicationError, PublicationContext, PublicationResult


class TelegramPublisher:
    supports_idempotency = False

    def __init__(self, bot: Bot) -> None:
        self.bot = bot

    async def publish(self, context: PublicationContext) -> PublicationResult:
        chunks = prepare_telegram_chunks(context.content_body)
        if not chunks:
            raise ValueError("Publication content is empty")

        first_message_id: str | None = None
        try:
            for chunk in chunks:
                sent = await self.bot.send_message(
                    context.channel_external_id,
                    chunk,
                    parse_mode="HTML",
                )
                if first_message_id is None:
                    first_message_id = str(sent.message_id)
        except TelegramNetworkError as exc:
            raise AmbiguousPublicationError(
                f"Telegram publication outcome is unknown for key {context.provider_operation_key}"
            ) from exc

        return PublicationResult(
            external_id=first_message_id or "unknown",
            message_count=len(chunks),
        )
