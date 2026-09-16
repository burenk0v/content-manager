from typing import Final


CONTENT_TRANSITIONS: Final[dict[str, frozenset[str]]] = {
    "draft": frozenset({"review"}),
    "review": frozenset({"draft", "approved"}),
    "approved": frozenset({"draft", "scheduled"}),
    "scheduled": frozenset({"approved", "draft", "publishing"}),
    "publishing": frozenset({"published", "failed", "scheduled"}),
    "published": frozenset({"archived"}),
    "failed": frozenset({"draft", "scheduled"}),
    "archived": frozenset(),
}


class InvalidContentTransition(ValueError):
    def __init__(self, current: str, target: str) -> None:
        allowed = sorted(CONTENT_TRANSITIONS.get(current, frozenset()))
        super().__init__(
            f"Invalid content transition: {current} -> {target}. Allowed: {allowed}"
        )
        self.current = current
        self.target = target
        self.allowed = tuple(allowed)


def allowed_transitions(current: str) -> tuple[str, ...]:
    return tuple(sorted(CONTENT_TRANSITIONS.get(current, frozenset())))


def can_transition(current: str, target: str) -> bool:
    return current == target or target in CONTENT_TRANSITIONS.get(current, frozenset())


def transition(current: str, target: str) -> str:
    if not can_transition(current, target):
        raise InvalidContentTransition(current, target)
    return target
