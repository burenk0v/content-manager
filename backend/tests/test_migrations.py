import os

from alembic import command
from alembic.config import Config
from sqlalchemy import create_engine, inspect, text


def test_legacy_schema_migrates_to_phase1_head(tmp_path, monkeypatch):
    db_path = tmp_path / "legacy.sqlite3"
    url = f"sqlite:///{db_path}"
    engine = create_engine(url)

    with engine.begin() as connection:
        connection.execute(text("CREATE TABLE topics (id INTEGER PRIMARY KEY, name VARCHAR NOT NULL, language VARCHAR NOT NULL)"))
        connection.execute(text("CREATE TABLE prompts (id INTEGER PRIMARY KEY, name VARCHAR NOT NULL, language VARCHAR NOT NULL, text TEXT NOT NULL)"))
        connection.execute(text("CREATE TABLE assistant_message_templates (id INTEGER PRIMARY KEY, name VARCHAR NOT NULL, language VARCHAR NOT NULL, text TEXT NOT NULL)"))
        connection.execute(text("CREATE TABLE publication_schedules (id INTEGER PRIMARY KEY, name VARCHAR NOT NULL, chat_id VARCHAR NOT NULL, chat_name VARCHAR, language VARCHAR NOT NULL, assistant_message TEXT NOT NULL, schedule_type VARCHAR NOT NULL, schedule_value VARCHAR NOT NULL, is_active BOOLEAN, last_run TIMESTAMP, created_at TIMESTAMP)"))
        connection.execute(text("CREATE TABLE post_drafts (id INTEGER PRIMARY KEY, schedule_id INTEGER NOT NULL, topic_id INTEGER, topic_name VARCHAR NOT NULL, language VARCHAR NOT NULL, generated_text TEXT NOT NULL, status VARCHAR NOT NULL, created_at TIMESTAMP, updated_at TIMESTAMP)"))

    monkeypatch.setenv("DATABASE_URL", url)
    config = Config(os.path.join(os.path.dirname(os.path.dirname(__file__)), "alembic.ini"))
    config.set_main_option("script_location", os.path.join(os.path.dirname(os.path.dirname(__file__)), "migrations"))
    command.upgrade(config, "head")

    inspector = inspect(engine)
    tables = set(inspector.get_table_names())
    assert {"workspaces", "channels", "contents", "content_versions", "publications", "audit_logs"} <= tables

    schedule_columns = {column["name"] for column in inspector.get_columns("publication_schedules")}
    assert {"prompt_id", "assistant_template_id", "timezone", "force_run_requested_at"} <= schedule_columns

    publication_columns = {column["name"] for column in inspector.get_columns("publications")}
    assert {"source_draft_id", "processing_started_at", "next_attempt_at", "attempt_count", "worker_id"} <= publication_columns

    content_columns = {column["name"] for column in inspector.get_columns("contents")}
    assert "status" in content_columns

    with engine.connect() as connection:
        version = connection.execute(text("SELECT version_num FROM alembic_version")).scalar_one()
    assert version == "0004_content_lifecycle"
