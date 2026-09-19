from __future__ import annotations

import json
import os
from pathlib import Path
import subprocess
import tempfile
import time

ROOT = Path(os.environ.get("PYTHON_VALIDATOR_DIR", "/var/lib/python-validator"))
INBOX = ROOT / "inbox"
OUTBOX = ROOT / "outbox"
MAX_TIMEOUT = 30
MAX_OUTPUT = 4000


def write_response(job_id: str, payload: dict) -> None:
    target = OUTBOX / f"{job_id}.json"
    temporary = OUTBOX / f".{job_id}.tmp"
    temporary.write_text(json.dumps(payload), encoding="utf-8")
    temporary.replace(target)


def run_job(job: Path) -> None:
    job_id = job.stem
    try:
        payload = json.loads(job.read_text(encoding="utf-8"))
        code = payload.get("code")
        if not isinstance(code, str) or not code.strip():
            raise ValueError("empty Python payload")
        timeout = max(1, min(int(payload.get("timeout", 8)), MAX_TIMEOUT))
        with tempfile.TemporaryDirectory() as directory:
            script = Path(directory) / "generated.py"
            script.write_text(code, encoding="utf-8")
            completed = subprocess.run(
                ["python", "-I", "-B", str(script)],
                cwd=directory,
                stdin=subprocess.DEVNULL,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                text=True,
                timeout=timeout,
                check=False,
            )
        if completed.returncode != 0:
            output = (completed.stderr or completed.stdout or "execution failed").strip()
            raise RuntimeError(output[-MAX_OUTPUT:])
        write_response(job_id, {"ok": True})
    except subprocess.TimeoutExpired:
        write_response(job_id, {"ok": False, "error": "Python execution exceeded sandbox timeout"})
    except Exception as exc:
        write_response(job_id, {"ok": False, "error": str(exc)[:MAX_OUTPUT]})
    finally:
        job.unlink(missing_ok=True)


def main() -> None:
    INBOX.mkdir(parents=True, exist_ok=True)
    OUTBOX.mkdir(parents=True, exist_ok=True)
    while True:
        jobs = sorted(INBOX.glob("*.json"))
        if not jobs:
            time.sleep(0.1)
            continue
        for job in jobs:
            run_job(job)


if __name__ == "__main__":
    main()
