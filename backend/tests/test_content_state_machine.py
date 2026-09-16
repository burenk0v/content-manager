import pytest

from src.app.domain.content_state_machine import (
    InvalidContentTransition,
    allowed_transitions,
    can_transition,
    transition,
)


def test_valid_transition_returns_target_state():
    assert transition("draft", "review") == "review"
    assert transition("publishing", "scheduled") == "scheduled"


def test_same_state_is_idempotent():
    assert transition("draft", "draft") == "draft"
    assert can_transition("archived", "archived") is True


def test_invalid_transition_raises_domain_error():
    with pytest.raises(InvalidContentTransition) as exc_info:
        transition("draft", "published")

    assert exc_info.value.current == "draft"
    assert exc_info.value.target == "published"
    assert exc_info.value.allowed == ("review",)


def test_unknown_state_has_no_allowed_transitions():
    assert allowed_transitions("unknown") == ()
    assert can_transition("unknown", "draft") is False
