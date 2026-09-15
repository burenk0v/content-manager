import pytest

from src.providers import TelegramPublisher, UnsupportedPublisherError
from src.providers.registry import ProviderRegistry, build_default_registry


def test_default_registry_resolves_telegram_publisher() -> None:
    publisher = build_default_registry().get("telegram", bot=object())
    assert isinstance(publisher, TelegramPublisher)


def test_registry_normalizes_platform_name() -> None:
    publisher = build_default_registry().get(" TELEGRAM ", bot=object())
    assert isinstance(publisher, TelegramPublisher)


def test_registry_rejects_unknown_platform() -> None:
    registry = ProviderRegistry()
    with pytest.raises(UnsupportedPublisherError, match="instagram"):
        registry.get("instagram")


def test_registry_rejects_empty_platform() -> None:
    registry = ProviderRegistry()
    with pytest.raises(UnsupportedPublisherError):
        registry.get("   ")
