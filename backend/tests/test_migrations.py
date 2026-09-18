import os
import subprocess
import sys
from pathlib import Path


def run_alembic(database_url: str, *args: str):
    env = os.environ.copy()
    env["DATABASE_URL"] = database_url
    env["PYTHONPATH"] = "."
    return subprocess.run(
        [sys.executable, "-m", "alembic", *args],
        cwd=Path(__file__).resolve().parents[1],
        env=env,
        capture_output=True,
        text=True,
    )


def test_alembic_rejects_sqlite_database_url(tmp_path):
    database_url = f"sqlite:///{tmp_path / 'fresh.db'}"
    result = run_alembic(database_url, "upgrade", "head")

    assert result.returncode != 0
    assert "DATABASE_URL must use PostgreSQL" in result.stderr


def test_alembic_rejects_sqlite_downgrade_database_url(tmp_path):
    database_url = f"sqlite:///{tmp_path / 'downgrade.db'}"
    result = run_alembic(database_url, "downgrade", "base")

    assert result.returncode != 0
    assert "DATABASE_URL must use PostgreSQL" in result.stderr
