"""Add explicit content lifecycle metadata.

Revision ID: 0004_content_lifecycle
Revises: 0003_publication_draft_link
"""
from alembic import op
from sqlalchemy import Column, String, inspect

revision = "0004_content_lifecycle"
down_revision = "0003_publication_draft_link"
branch_labels = None
depends_on = None


def upgrade():
    bind = op.get_bind()
    inspector = inspect(bind)
    if "contents" not in inspector.get_table_names():
        return
    columns = {column["name"] for column in inspector.get_columns("contents")}
    if "status" not in columns:
        op.add_column("contents", Column("status", String, nullable=False, server_default="draft"))
    indexes = {index["name"] for index in inspector.get_indexes("contents")}
    if "ix_contents_status" not in indexes:
        op.create_index("ix_contents_status", "contents", ["status"])


def downgrade():
    bind = op.get_bind()
    inspector = inspect(bind)
    if "contents" not in inspector.get_table_names():
        return
    indexes = {index["name"] for index in inspector.get_indexes("contents")}
    if "ix_contents_status" in indexes:
        op.drop_index("ix_contents_status", table_name="contents")
    columns = {column["name"] for column in inspector.get_columns("contents")}
    if "status" in columns:
        op.drop_column("contents", "status")
