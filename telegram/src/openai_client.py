import os
import logging
from openai import OpenAI
from tenacity import retry, stop_after_attempt, wait_exponential, retry_if_exception_type

logger = logging.getLogger(__name__)
# Enable debug logging when OPENAI_DEBUG is set (true/1/yes)
debug_enabled = os.getenv("OPENAI_DEBUG", "false").lower() in ("1", "true", "yes")
logging.basicConfig(level=logging.DEBUG if debug_enabled else logging.INFO)


def _truncate(s: str, n: int = 1000) -> str:
    if s is None:
        return ""
    return s if len(s) <= n else s[:n] + "...[truncated]"

OPENAI_API_KEY = os.getenv("OPENAI_API_KEY")


class OpenAIClient:
    def __init__(self, model: str | None = None, max_retries: int = 3):
        self.model = model or os.getenv("OPENAI_MODEL", "gpt-3.5-turbo")
        self.max_retries = max_retries
        self.client = OpenAI(api_key=OPENAI_API_KEY) if OPENAI_API_KEY else OpenAI()

    def _build_messages(self, prompt: str, system_message: str | None = None) -> list[dict[str, str]]:
        messages = []
        if system_message:
            messages.append({"role": "system", "content": system_message})
        messages.append({"role": "user", "content": prompt})
        return messages

    @retry(stop=stop_after_attempt(3), wait=wait_exponential(multiplier=1, min=1, max=8),
           retry=retry_if_exception_type(Exception))
    def chat(self, prompt: str, system_message: str | None = None) -> str:
        if not OPENAI_API_KEY:
            logger.error("OpenAI API key not configured")
            return "OpenAI API key not configured."

        messages = self._build_messages(prompt, system_message)
        logger.info("Sending prompt to OpenAI")
        if debug_enabled:
            logger.debug("OpenAI prompt: %s", _truncate(prompt, 2000))

        response = self.client.chat.completions.create(
            model=self.model,
            messages=messages,
            temperature=0.7,
            max_tokens=1000,
        )

        try:
            text = response.choices[0].message.content.strip()
        except Exception:
            text = ""
            try:
                text = response.choices[0]["message"]["content"].strip()
            except Exception:
                pass

        logger.info("Received response from OpenAI (len=%d)", len(text))
        if debug_enabled:
            logger.debug("OpenAI response: %s", _truncate(text, 4000))
        return text
