from __future__ import annotations

import os
from dataclasses import dataclass
from typing import Protocol

from src.app.ai_generation import GenerationError


@dataclass(frozen=True)
class TransformationRequest:
    body: str
    platform: str
    language: str
    instructions: str | None = None
    model: str | None = None


class ContentTransformer(Protocol):
    name: str

    def transform(self, request: TransformationRequest) -> str: ...


class OpenAIContentTransformer:
    name = "openai"

    def __init__(self) -> None:
        try:
            from openai import OpenAI
        except ImportError as exc:  # pragma: no cover
            raise GenerationError("OpenAI provider is not installed") from exc
        api_key = os.getenv("OPENAI_API_KEY")
        if not api_key:
            raise GenerationError("OPENAI_API_KEY is not configured")
        self._client = OpenAI(api_key=api_key)
        self._default_model = os.getenv("OPENAI_MODEL", "gpt-4o-mini")

    def transform(self, request: TransformationRequest) -> str:
        system = (
            "You are a professional content editor. Adapt the source content for the target channel. "
            "Preserve factual meaning, language, and important details. Do not invent claims. "
            "Return only the final publishable text, with no commentary about the transformation."
        )
        user = (
            f"Target platform: {request.platform}\n"
            f"Language: {request.language}\n"
            f"Additional instructions: {request.instructions or 'none'}\n\n"
            f"Source content:\n{request.body}"
        )
        try:
            response = self._client.chat.completions.create(
                model=request.model or self._default_model,
                messages=[{"role": "system", "content": system}, {"role": "user", "content": user}],
                temperature=0.5,
            )
        except Exception as exc:
            raise GenerationError("AI transformation request failed") from exc
        text = (response.choices[0].message.content or "").strip()
        if not text:
            raise GenerationError("AI transformer returned an empty response")
        return text


def get_content_transformer() -> ContentTransformer:
    provider = os.getenv("AI_TRANSFORMATION_PROVIDER", os.getenv("AI_GENERATION_PROVIDER", "openai")).strip().lower()
    if provider == "openai":
        return OpenAIContentTransformer()
    raise GenerationError(f"Unsupported AI transformation provider: {provider}")
