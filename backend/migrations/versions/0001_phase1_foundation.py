"""Phase 1 foundation schema.

Revision ID: 0001_phase1_foundation
Revises:
"""
from alembic import op
from sqlalchemy import inspect, text

from src.app.db import Base
from src.app import models  # noqa: F401

revision = "0001_phase1_foundation"
down_revision = None
branch_labels = None
depends_on = None


LEGACY_COLUMNS = {
    "publication_schedules": {
        "prompt_id": "INTEGER",
        "assistant_template_id": "INTEGER",
        "timezone": "VARCHAR NOT NULL DEFAULT 'UTC'",
        "force_run_requested_at": "TIMESTAMP NULL",
    }
}


def upgrade():
    bind = op.get_bind()

    # create_all is deliberately used inside the migration, not application startup:
    # it creates missing legacy tables on a fresh install while remaining harmless for
    # databases that already contain the original schema.
    Base.metadata.create_all(bind=bind)

    inspector = inspect(bind)
    for table_name, columns in LEGACY_COLUMNS.items():
        if table_name not in inspector.get_table_names():
            continue
        existing = {column["name"] for column in inspector.get_columns(table_name)}
        for column_name, definition in columns.items():
            if column_name not in existing:
                if bind.dialect.name == "postgresql":
                    bind.execute(text(
                        f"ALTER TABLE {table_name} ADD COLUMN IF NOT EXISTS "
                        f"{column_name} {definition}"
                    ))
                else:
                    bind.execute(text(
                        f"ALTER TABLE {table_name} ADD COLUMN {column_name} {definition}"
                    ))

    if bind.dialect.name == "postgresql":
        inspector = inspect(bind)
        if "post_drafts" in inspector.get_table_names():
            draft_columns = {c["name"]: c for c in inspector.get_columns("post_drafts")}
            topic_id = draft_columns.get("topic_id")
            if topic_id and topic_id.get("nullable") is False:
                bind.execute(text(
                    "ALTER TABLE post_drafts ALTER COLUMN topic_id DROP NOT NULL"
                ))


def downgrade():
    # Keep legacy tables intact on downgrade; only remove Phase 1 tables.
    for table_name in (
        "audit_logs",
        "publications",
        "content_versions",
        "contents",
        "channels",
        "workspaces",
    ):
        op.drop_table(table_name)
