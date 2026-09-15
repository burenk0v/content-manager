from collections.abc import Callable
from typing import Any

from .base import Publisher
from .telegram import TelegramPublisher


class UnsupportedPublisherError(RuntimeError):
    """Raised when no publisher is registered for a channel platform."""


PublisherFactory = Callable[..., Publisher]


class ProviderRegistry:
    def __init__(self) -> None:
        self._factories: dict[str, PublisherFactory] = {}

    def register(self, platform: str, factory: PublisherFactory) -> None:
        key = platform.strip().lower()
        if not key:
            raise ValueError("Provider platform cannot be empty")
        self._factories[key] = factory

    def get(self, platform: str, **kwargs: Any) -> Publisher:
        key = platform.strip().lower()
        factory = self._factories.get(key)
        if factory is None:
            raise UnsupportedPublisherError(f"Unsupported publication platform: {platform}")
        return factory(**kwargs)


def build_default_registry() -> ProviderRegistry:
    registry = ProviderRegistry()
    registry.register("telegram", TelegramPublisher)
    return registry


registry = build_default_registry()
