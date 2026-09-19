from __future__ import annotations

import json
import os
from pathlib import Path
import time
import uuid


class PythonSandboxError(Exception):
    pass


DEFAULT_TIMEOUT_SECONDS = 8
MAX_TIMEOUT_SECONDS = 30


def _timeout_seconds() -> int:
    try:
        value = int(os.environ.get("PYTHON_VALIDATOR_TIMEOUT_SECONDS", str(DEFAULT_TIMEOUT_SECONDS)))
    except ValueError:
        value = DEFAULT_TIMEOUT_SECONDS
    return max(1, min(value, MAX_TIMEOUT_SECONDS))


def execute_python_blocks(blocks: list[str]) -> None:
    if not blocks:
        return
    root = Path(os.environ.get("PYTHON_VALIDATOR_DIR", "/var/lib/python-validator"))
    inbox = root / "inbox"
    outbox = root / "outbox"
    inbox.mkdir(parents=True, exist_ok=True)
    outbox.mkdir(parents=True, exist_ok=True)
    job_id = uuid.uuid4().hex
    request = inbox / f"{job_id}.json"
    response = outbox / f"{job_id}.json"
    request.write_text(
        json.dumps({"code": "\\n\\n".join(blocks), "timeout": _timeout_seconds()}),
        encoding="utf-8",
    )
    deadline = time.monotonic() + _timeout_seconds() + 5
    try:
        while time.monotonic() < deadline:
            if response.exists():
                try:
                    result = json.loads(response.read_text(encoding="utf-8"))
                finally:
                    response.unlink(missing_ok=True)
                if result.get("ok"):
                    return
                raise PythonSandboxError(result.get("error") or "Python sandbox validation failed")
            time.sleep(0.1)
    finally:
        request.unlink(missing_ok=True)
    raise PythonSandboxError("Python sandbox validator timed out or is unavailable")
