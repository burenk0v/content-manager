"""Add publication processing and retry fields.

Revision ID: 0002_publication_state
Revises: 0001_phase1_foundation
"""
from alembic import op
import sqlalchemy as sa

revision = "0002_publication_state"
down_revision = "0001_phase1_foundation"
branch_labels = None
depends_on = None


def upgrade():
    op.add_column("publications", sa.Column("processing_started_at", sa.DateTime(), nullable=True))
    op.add_column("publications", sa.Column("next_attempt_at", sa.DateTime(), nullable=True))
    op.add_column("publications", sa.Column("attempt_count", sa.Integer(), nullable=False, server_default="0"))
    op.add_column("publications", sa.Column("worker_id", sa.String(), nullable=True))
    op.create_index("ix_publications_next_attempt_at", "publications", ["next_attempt_at"])


def downgrade():
    op.drop_index("ix_publications_next_attempt_at", table_name="publications")
    op.drop_column("publications", "worker_id")
    op.drop_column("publications", "attempt_count")
    op.drop_column("publications", "next_attempt_at")
    op.drop_column("publications", "processing_started_at")
