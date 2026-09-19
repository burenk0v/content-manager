from __future__ import annotations

import re
from difflib import SequenceMatcher

from sqlalchemy.orm import Session

from src.app.models import Content

STOPWORDS = {
    "a", "an", "the", "and", "or", "of", "to", "in", "on", "for", "with", "how", "what", "why",
    "как", "что", "и", "или", "для", "в", "на", "с", "из", "по", "почему", "работает",
}


def normalize_topic(topic: str) -> str:
    value = (topic or "").casefold().replace("_", " ")
    value = re.sub(r"[^\w\s+#.-]", " ", value, flags=re.UNICODE)
    return re.sub(r"\s+", " ", value).strip()


def topic_tokens(topic: str) -> set[str]:
    return {
        token.strip(".-+#")
        for token in normalize_topic(topic).split()
        if token.strip(".-+#") and token.strip(".-+#") not in STOPWORDS
    }


def topic_similarity(left: str, right: str) -> float:
    a, b = normalize_topic(left), normalize_topic(right)
    if not a or not b:
        return 0.0
    if a == b or a in b or b in a:
        return 1.0
    ta, tb = topic_tokens(a), topic_tokens(b)
    if not ta or not tb:
        return SequenceMatcher(None, a, b).ratio()
    overlap = len(ta & tb) / max(1, min(len(ta), len(tb)))
    return max(overlap, SequenceMatcher(None, a, b).ratio())


def load_topic_memory(db: Session, profile_id: int) -> list[tuple[str, str]]:
    rows = (
        db.query(Content.title, Content.status)
        .filter(
            Content.profile_id == profile_id,
            Content.title.isnot(None),
            Content.title != "AI generation in progress",
        )
        .order_by(Content.created_at.desc(), Content.id.desc())
        .limit(500)
        .all()
    )
    return [(str(title).strip(), str(status)) for title, status in rows if str(title).strip()]


def find_duplicate_topic(topic: str, memory: list[tuple[str, str]], threshold: float = 0.82) -> tuple[str, str, float] | None:
    for existing, status in memory:
        score = topic_similarity(topic, existing)
        if score >= threshold:
            return existing, status, score
    return None
