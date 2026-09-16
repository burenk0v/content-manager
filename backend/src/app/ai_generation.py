from __future__ import annotations

import os
from dataclasses import dataclass
from typing import Protocol


class GenerationProvider(Protocol):
    name: str

    def generate(self, *, prompt: str, system_message: str | None, model: str | None) -> str: ...


@dataclass(frozen=True)
class GenerationRequest:
    prompt: str
    system_message: str | None = None
    model: str | None = None


class GenerationError(RuntimeError):
    pass


class OpenAIGenerationProvider:
    name = "openai"

    def __init__(self) -> None:
        try:
            from openai import OpenAI
        except ImportError as exc:  # pragma: no cover - dependency is part of the backend image
            raise GenerationError("OpenAI provider is not installed") from exc

        api_key = os.getenv("OPENAI_API_KEY")
        if not api_key:
            raise GenerationError("OPENAI_API_KEY is not configured")
        self._client = OpenAI(api_key=api_key)
        self._default_model = os.getenv("OPENAI_MODEL", "gpt-4o-mini")

    def generate(self, *, prompt: str, system_message: str | None, model: str | None) -> str:
        messages: list[dict[str, str]] = []
        if system_message:
            messages.append({"role": "system", "content": system_message})
        messages.append({"role": "user", "content": prompt})
        try:
            response = self._client.chat.completions.create(
                model=model or self._default_model,
                messages=messages,
                temperature=0.7,
            )
        except Exception as exc:
            raise GenerationError("AI provider request failed") from exc

        text = response.choices[0].message.content or ""
        text = text.strip()
        if not text:
            raise GenerationError("AI provider returned an empty response")
        return text


def get_generation_provider() -> GenerationProvider:
    provider = os.getenv("AI_GENERATION_PROVIDER", "openai").strip().lower()
    if provider == "openai":
        return OpenAIGenerationProvider()
    raise GenerationError(f"Unsupported AI generation provider: {provider}")
