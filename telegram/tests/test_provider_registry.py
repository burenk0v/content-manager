import pytest

from src.providers import TelegramPublisher, UnsupportedPublisherError
from src.providers.base import ProviderCapabilities
from src.providers.registry import ProviderRegistry, UnsupportedReconcilerError, build_default_registry


def test_default_registry_resolves_telegram_publisher() -> None:
    registry = build_default_registry()
    publisher = registry.get("telegram", bot=object())
    assert isinstance(publisher, TelegramPublisher)
    assert publisher.capabilities == ProviderCapabilities(
        supports_idempotency=False,
        supports_reconciliation=False,
    )
    assert registry.capabilities("telegram", bot=object()) == publisher.capabilities


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


def test_registry_reports_missing_reconciler() -> None:
    registry = build_default_registry()
    with pytest.raises(UnsupportedReconcilerError, match="telegram"):
        registry.get_reconciler("telegram")
