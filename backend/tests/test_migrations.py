import os
import subprocess
import sys
from pathlib import Path


def test_alembic_bootstraps_current_schema_from_empty_database(tmp_path):
    database_url = f"sqlite:///{tmp_path / 'fresh.db'}"
    env = os.environ.copy()
    env["DATABASE_URL"] = database_url
    env["PYTHONPATH"] = "."

    result = subprocess.run(
        [sys.executable, "-m", "alembic", "upgrade", "head"],
        cwd=Path(__file__).resolve().parents[1],
        env=env,
        capture_output=True,
        text=True,
    )
    assert result.returncode == 0, result.stderr

    from sqlalchemy import create_engine, inspect

    engine = create_engine(database_url)
    inspector = inspect(engine)
    tables = set(inspector.get_table_names())
    assert tables >= {
        "users",
        "workspaces",
        "channels",
        "contents",
        "content_versions",
        "publications",
        "audit_logs",
    }
    assert not tables.intersection({
        "topics",
        "prompts",
        "assistant_message_templates",
        "publication_schedules",
        "post_drafts",
    })

    publication_columns = {column["name"] for column in inspector.get_columns("publications")}
    assert {
        "processing_token",
        "lease_heartbeat_at",
        "next_attempt_at",
        "attempt_count",
        "worker_id",
        "idempotency_key",
    } <= publication_columns

    publication_indexes = {index["name"]: index for index in inspector.get_indexes("publications")}
    assert publication_indexes["uq_publications_content_channel"]["unique"] is True
    assert publication_indexes["uq_publications_content_channel"]["column_names"] == ["content_id", "channel_id"]
    assert "ix_publications_processing_token" in publication_indexes
    assert "ix_publications_lease_heartbeat_at" in publication_indexes

    with engine.connect() as connection:
        version = connection.exec_driver_sql("SELECT version_num FROM alembic_version").scalar_one()
    assert version == "0001_initial"
