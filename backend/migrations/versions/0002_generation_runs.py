"""Persist AI generation runs and their resulting content versions."""

from alembic import op
import sqlalchemy as sa

revision = "0002_generation_runs"
down_revision = "0001_initial"
branch_labels = None
depends_on = None


def upgrade():
    op.create_table(
        "generation_runs",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("content_id", sa.Integer(), sa.ForeignKey("contents.id", ondelete="CASCADE"), nullable=False),
        sa.Column("content_version_id", sa.Integer(), sa.ForeignKey("content_versions.id", ondelete="SET NULL"), nullable=True),
        sa.Column("provider", sa.String(), nullable=False),
        sa.Column("model", sa.String(), nullable=True),
        sa.Column("status", sa.String(), nullable=False, server_default="running"),
        sa.Column("prompt", sa.Text(), nullable=False),
        sa.Column("error_message", sa.Text(), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("completed_at", sa.DateTime(), nullable=True),
    )
    op.create_index("ix_generation_runs_id", "generation_runs", ["id"])
    op.create_index("ix_generation_runs_content_id", "generation_runs", ["content_id"])
    op.create_index("ix_generation_runs_content_version_id", "generation_runs", ["content_version_id"])
    op.create_index("ix_generation_runs_status", "generation_runs", ["status"])


def downgrade():
    op.drop_index("ix_generation_runs_status", table_name="generation_runs")
    op.drop_index("ix_generation_runs_content_version_id", table_name="generation_runs")
    op.drop_index("ix_generation_runs_content_id", table_name="generation_runs")
    op.drop_index("ix_generation_runs_id", table_name="generation_runs")
    op.drop_table("generation_runs")
