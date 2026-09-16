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


def test_alembic_bootstraps_current_schema_from_empty_database(tmp_path):
    database_url = f"sqlite:///{tmp_path / 'fresh.db'}"
    result = run_alembic(database_url, "upgrade", "head")
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
        "publication_operations",
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
        "content_version_id",
        "processing_token",
        "lease_heartbeat_at",
        "next_attempt_at",
        "attempt_count",
        "worker_id",
        "idempotency_key",
    } <= publication_columns

    publication_indexes = {index["name"]: index for index in inspector.get_indexes("publications")}
    assert publication_indexes["uq_publications_content_channel"]["unique"] == 1
    assert publication_indexes["uq_publications_content_channel"]["column_names"] == ["content_id", "channel_id"]
    assert "ix_publications_processing_token" in publication_indexes
    assert "ix_publications_lease_heartbeat_at" in publication_indexes

    operation_indexes = {index["name"]: index for index in inspector.get_indexes("publication_operations")}
    assert "ix_publication_operations_publication_id" in operation_indexes
    assert "ix_publication_operations_operation_key" in operation_indexes

    with engine.connect() as connection:
        version = connection.exec_driver_sql("SELECT version_num FROM alembic_version").scalar_one()
    assert version == "0001_initial"


def test_alembic_can_downgrade_fresh_schema_to_base(tmp_path):
    database_url = f"sqlite:///{tmp_path / 'downgrade.db'}"
    assert run_alembic(database_url, "upgrade", "head").returncode == 0

    result = run_alembic(database_url, "downgrade", "base")
    assert result.returncode == 0, result.stderr

    from sqlalchemy import create_engine, inspect

    engine = create_engine(database_url)
    inspector = inspect(engine)
    assert set(inspector.get_table_names()) == {"alembic_version"}
