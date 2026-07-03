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
_openai_client = OpenAI(api_key=OPENAI_API_KEY) if OPENAI_API_KEY else OpenAI()


class OpenAIClient:
    def __init__(self, model: str | None = None, max_retries: int = 3):
        self.model = model or os.getenv("OPENAI_MODEL", "gpt-3.5-turbo")
        self.max_retries = max_retries

    @retry(stop=stop_after_attempt(3), wait=wait_exponential(multiplier=1, min=1, max=8),
           retry=retry_if_exception_type(Exception))
    def _call_api(self, prompt: str):
        # Use the new OpenAI client API
        return _openai_client.chat.completions.create(
            model=self.model,
            messages=[
                {
                    "role": "debug",
                    "content": "Ты большой специалист в автоматизации тестирования",
                },
                {
                    "role": "system",
                    "content": 
                        "Use markdown formatting for telegram messages. "
                        "If the answer is a code snippet, provide it in a code block. "
                        "If the answer is a list, provide it as a numbered list. "
                        "If the answer is a table, provide it in markdown table format. "
                        "Try to doesnot exceed 4000 characters in the answer.",
                },
                {
                    "role": "user",
                    "content": prompt,
                },
            ],
            max_tokens=512,
            temperature=0.7,
        )

    def chat(self, prompt: str) -> str:
        if not OPENAI_API_KEY:
            logger.error("OpenAI API key not configured")
            return "OpenAI API key not configured."

        try:
            logger.info("Sending prompt to OpenAI")
            if debug_enabled:
                logger.debug("OpenAI prompt: %s", _truncate(prompt, 2000))

            resp = self._call_api(prompt)
            # response structure from new client: resp.choices[0].message.content
            try:
                text = resp.choices[0].message.content.strip()
            except Exception:
                # fallback to dict-style access
                text = (getattr(resp.choices[0].message, 'content', None) or resp.choices[0].message.get('content'))
                if text:
                    text = text.strip()
                else:
                    text = ''

            logger.info("Received response from OpenAI (len=%d)", len(text))
            if debug_enabled:
                logger.debug("OpenAI response: %s", _truncate(text, 4000))
            return text
        except Exception as e:
            logger.exception("OpenAI request failed after retries: %s", e)
            return f"OpenAI error: {e}"
