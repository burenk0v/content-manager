from aiogram import Bot
from aiogram.exceptions import TelegramBadRequest, TelegramForbiddenError, TelegramNetworkError

from telegram_format import prepare_telegram_chunks
from .base import AmbiguousPublicationError, PermanentPublicationError, ProviderCapabilities, PublicationContext, PublicationResult


class TelegramPublisher:
    capabilities = ProviderCapabilities(
        supports_idempotency=False,
        supports_reconciliation=False,
    )

    def __init__(self, bot: Bot) -> None:
        self.bot = bot

    async def publish(self, context: PublicationContext) -> PublicationResult:
        chunks = prepare_telegram_chunks(context.content_body)
        if not chunks:
            raise PermanentPublicationError("Publication content is empty")

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
        except (TelegramBadRequest, TelegramForbiddenError) as exc:
            raise PermanentPublicationError(str(exc)) from exc

        if first_message_id is None:
            raise PermanentPublicationError("Telegram provider returned no message id")

        return PublicationResult(
            external_id=first_message_id,
            message_count=len(chunks),
        )
