"""Persist channel-specific content variants."""

from alembic import op
import sqlalchemy as sa

revision = "0003_content_variants"
down_revision = "0002_generation_runs"
branch_labels = None
depends_on = None


def upgrade():
    op.create_table(
        "content_variants",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("content_id", sa.Integer(), sa.ForeignKey("contents.id", ondelete="CASCADE"), nullable=False),
        sa.Column("content_version_id", sa.Integer(), sa.ForeignKey("content_versions.id", ondelete="CASCADE"), nullable=False),
        sa.Column("channel_id", sa.Integer(), sa.ForeignKey("channels.id", ondelete="CASCADE"), nullable=False),
        sa.Column("version", sa.Integer(), nullable=False),
        sa.Column("body", sa.Text(), nullable=False),
        sa.Column("provider", sa.String(), nullable=False),
        sa.Column("model", sa.String(), nullable=True),
        sa.Column("status", sa.String(), nullable=False, server_default="draft"),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.UniqueConstraint("content_version_id", "channel_id", "version", name="uq_content_variants_source_channel_version"),
    )
    op.create_index("ix_content_variants_id", "content_variants", ["id"])
    op.create_index("ix_content_variants_content_id", "content_variants", ["content_id"])
    op.create_index("ix_content_variants_content_version_id", "content_variants", ["content_version_id"])
    op.create_index("ix_content_variants_channel_id", "content_variants", ["channel_id"])
    op.create_index("ix_content_variants_status", "content_variants", ["status"])


def downgrade():
    op.drop_index("ix_content_variants_status", table_name="content_variants")
    op.drop_index("ix_content_variants_channel_id", table_name="content_variants")
    op.drop_index("ix_content_variants_content_version_id", table_name="content_variants")
    op.drop_index("ix_content_variants_content_id", table_name="content_variants")
    op.drop_index("ix_content_variants_id", table_name="content_variants")
    op.drop_table("content_variants")
