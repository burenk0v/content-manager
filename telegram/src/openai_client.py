import os
import logging
import time
import openai
from tenacity import retry, stop_after_attempt, wait_exponential, retry_if_exception_type

logger = logging.getLogger(__name__)
logging.basicConfig(level=logging.INFO)

OPENAI_API_KEY = os.getenv("OPENAI_API_KEY")
if OPENAI_API_KEY:
    openai.api_key = OPENAI_API_KEY


class OpenAIClient:
    def __init__(self, model: str | None = None, max_retries: int = 3):
        self.model = model or os.getenv("OPENAI_MODEL", "gpt-3.5-turbo")
        self.max_retries = max_retries

    @retry(stop=stop_after_attempt(3), wait=wait_exponential(multiplier=1, min=1, max=8),
           retry=retry_if_exception_type(Exception))
    def _call_api(self, prompt: str):
        return openai.ChatCompletion.create(
            model=self.model,
            messages=[{"role": "user", "content": prompt}],
            max_tokens=512,
            temperature=0.7,
        )

    def chat(self, prompt: str) -> str:
        if not OPENAI_API_KEY:
            logger.error("OpenAI API key not configured")
            return "OpenAI API key not configured."

        try:
            logger.info("Sending prompt to OpenAI")
            resp = self._call_api(prompt)
            text = resp.choices[0].message.content.strip()
            logger.info("Received response from OpenAI (len=%d)", len(text))
            return text
        except Exception as e:
            logger.exception("OpenAI request failed after retries: %s", e)
            return f"OpenAI error: {e}"
