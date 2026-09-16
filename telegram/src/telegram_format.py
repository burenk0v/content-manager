import re
from html import escape

TELEGRAM_MESSAGE_LIMIT = 4096
SAFE_CHUNK_SIZE = 3800


def prepare_telegram_content(text: str) -> str:
    text = (text or "").strip()
    if not text:
        return text
    if re.search(r"</?[a-zA-Z][^>]*>", text):
        allowed = {"b", "i", "u", "code", "pre", "a"}
        stack: list[str] = []

        def replace(match: re.Match[str]) -> str:
            raw, tag, attrs = match.group(0), match.group(1).lower(), match.group(2) or ""
            if raw.startswith("</"):
                if tag in allowed and stack and stack[-1] == tag:
                    stack.pop()
                    return f"</{tag}>"
                return ""
            if tag not in allowed:
                return ""
            if tag == "a":
                href = re.search(r'href=["\']([^"\']+)["\']', attrs, re.I)
                if not href or not href.group(1).startswith(("http://", "https://")):
                    return ""
                stack.append(tag)
                return f'<a href="{escape(href.group(1), quote=True)}">'
            stack.append(tag)
            return f"<{tag}>"

        result = re.sub(r"</?([a-zA-Z0-9]+)([^>]*)>", replace, text)
        while stack:
            result += f"</{stack.pop()}>"
        return result

    lines, in_code, code_lines = [], False, []
    for line in text.splitlines():
        if line.strip().startswith("```"):
            if in_code:
                lines.append(f"<pre><code>{escape(chr(10).join(code_lines))}</code></pre>")
                code_lines = []
            in_code = not in_code
            continue
        if in_code:
            code_lines.append(line)
            continue
        rendered = escape(line)
        rendered = re.sub(r'\*\*(.+?)\*\*', r'<b>\1</b>', rendered)
        rendered = re.sub(r'__(.+?)__', r'<b>\1</b>', rendered)
        rendered = re.sub(r'\*(.+?)\*', r'<i>\1</i>', rendered)
        rendered = re.sub(r'_(.+?)_', r'<i>\1</i>', rendered)
        rendered = re.sub(r'`([^`]+)`', r'<code>\1</code>', rendered)
        lines.append("• " + rendered[2:] if rendered.startswith("- ") else rendered)
    if in_code:
        lines.append(f"<pre><code>{escape(chr(10).join(code_lines))}</code></pre>")
    return "\n".join(lines)


def _plain_chunks(text: str, size: int = SAFE_CHUNK_SIZE) -> list[str]:
    text = re.sub(r"<[^>]+>", "", text)
    text = re.sub(r"\n{3,}", "\n\n", text).strip()
    if not text:
        return []
    return [escape(text[i:i + size]) for i in range(0, len(text), size)]


def prepare_telegram_chunks(text: str) -> list[str]:
    formatted = prepare_telegram_content(text)
    if not formatted:
        return []
    if len(formatted) <= TELEGRAM_MESSAGE_LIMIT:
        return [formatted]

    # Keep a conservative margin for Telegram's parsed-message limit. If
    # formatting makes the result too large, fall back to safe plain-text
    # chunks rather than risking a BadRequest from Telegram.
    return _plain_chunks(formatted)
