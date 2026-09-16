from collections.abc import Callable
from typing import Any

from .base import ProviderCapabilities, ProviderReconciler, Publisher
from .telegram import TelegramPublisher


class UnsupportedPublisherError(RuntimeError):
    """Raised when no publisher is registered for a channel platform."""


class UnsupportedReconcilerError(RuntimeError):
    """Raised when a provider cannot reconcile an ambiguous operation."""


PublisherFactory = Callable[..., Publisher]
ReconcilerFactory = Callable[..., ProviderReconciler]


class ProviderRegistry:
    def __init__(self) -> None:
        self._factories: dict[str, PublisherFactory] = {}
        self._reconciler_factories: dict[str, ReconcilerFactory] = {}

    def register(self, platform: str, factory: PublisherFactory) -> None:
        key = platform.strip().lower()
        if not key:
            raise ValueError("Provider platform cannot be empty")
        self._factories[key] = factory

    def register_reconciler(self, platform: str, factory: ReconcilerFactory) -> None:
        key = platform.strip().lower()
        if not key:
            raise ValueError("Provider platform cannot be empty")
        self._reconciler_factories[key] = factory

    def get(self, platform: str, **kwargs: Any) -> Publisher:
        key = platform.strip().lower()
        factory = self._factories.get(key)
        if factory is None:
            raise UnsupportedPublisherError(f"Unsupported publication platform: {platform}")
        return factory(**kwargs)

    def get_reconciler(self, platform: str, **kwargs: Any) -> ProviderReconciler:
        key = platform.strip().lower()
        factory = self._reconciler_factories.get(key)
        if factory is None:
            raise UnsupportedReconcilerError(
                f"Provider reconciliation is unsupported for platform: {platform}"
            )
        return factory(**kwargs)

    def capabilities(self, platform: str, **kwargs: Any) -> ProviderCapabilities:
        publisher = self.get(platform, **kwargs)
        return publisher.capabilities


def build_default_registry() -> ProviderRegistry:
    registry = ProviderRegistry()
    registry.register("telegram", TelegramPublisher)
    return registry


registry = build_default_registry()
