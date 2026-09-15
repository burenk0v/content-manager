from typing import Final

from fastapi import HTTPException

CONTENT_TRANSITIONS: Final[dict[str, frozenset[str]]] = {
    "draft": frozenset({"review"}),
    "review": frozenset({"draft", "approved"}),
    "approved": frozenset({"draft", "scheduled"}),
    "scheduled": frozenset({"approved", "publishing"}),
    "publishing": frozenset({"published", "failed"}),
    "published": frozenset({"archived"}),
    "failed": frozenset({"draft", "scheduled"}),
    "archived": frozenset(),
}


def can_transition(current: str, target: str) -> bool:
    return target in CONTENT_TRANSITIONS.get(current, frozenset())


def transition_or_raise(current: str, target: str) -> None:
    if current == target:
        return
    if not can_transition(current, target):
        allowed = sorted(CONTENT_TRANSITIONS.get(current, frozenset()))
        detail = f"Invalid content transition: {current} -> {target}. Allowed: {allowed}"
        raise HTTPException(status_code=409, detail=detail)
