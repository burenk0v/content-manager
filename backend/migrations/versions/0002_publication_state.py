"""Add publication processing and retry fields.

Revision ID: 0002_publication_state
Revises: 0001_phase1_foundation
"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy import inspect

revision = "0002_publication_state"
down_revision = "0001_phase1_foundation"
branch_labels = None
depends_on = None


def upgrade():
    bind = op.get_bind()
    inspector = inspect(bind)
    columns = {column["name"] for column in inspector.get_columns("publications")}

    if "processing_started_at" not in columns:
        op.add_column("publications", sa.Column("processing_started_at", sa.DateTime(), nullable=True))
    if "next_attempt_at" not in columns:
        op.add_column("publications", sa.Column("next_attempt_at", sa.DateTime(), nullable=True))
    if "attempt_count" not in columns:
        op.add_column("publications", sa.Column("attempt_count", sa.Integer(), nullable=False, server_default="0"))
    if "worker_id" not in columns:
        op.add_column("publications", sa.Column("worker_id", sa.String(), nullable=True))

    indexes = {index["name"] for index in inspector.get_indexes("publications")}
    if "ix_publications_next_attempt_at" not in indexes:
        op.create_index("ix_publications_next_attempt_at", "publications", ["next_attempt_at"])


def downgrade():
    bind = op.get_bind()
    inspector = inspect(bind)
    indexes = {index["name"] for index in inspector.get_indexes("publications")}
    if "ix_publications_next_attempt_at" in indexes:
        op.drop_index("ix_publications_next_attempt_at", table_name="publications")
    columns = {column["name"] for column in inspector.get_columns("publications")}
    for column in ("worker_id", "attempt_count", "next_attempt_at", "processing_started_at"):
        if column in columns:
            op.drop_column("publications", column)
