"""Add persistent autonomous content profiles."""

from alembic import op
import sqlalchemy as sa

revision = "0005_content_profiles"
down_revision = "0004_persistence_guards"
branch_labels = None
depends_on = None


def upgrade():
    op.create_table(
        "content_profiles",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("workspace_id", sa.Integer(), sa.ForeignKey("workspaces.id", ondelete="CASCADE"), nullable=False),
        sa.Column("channel_id", sa.Integer(), sa.ForeignKey("channels.id", ondelete="CASCADE"), nullable=False),
        sa.Column("name", sa.String(), nullable=False),
        sa.Column("language", sa.String(), nullable=False),
        sa.Column("topic_niche", sa.Text(), nullable=True),
        sa.Column("tone", sa.String(), nullable=True),
        sa.Column("content_format", sa.String(), nullable=True),
        sa.Column("rules", sa.Text(), nullable=True),
        sa.Column("timezone", sa.String(), nullable=False),
        sa.Column("schedule_type", sa.String(), nullable=False),
        sa.Column("schedule_value", sa.String(), nullable=False),
        sa.Column("is_active", sa.Boolean(), nullable=False),
        sa.Column("last_run", sa.DateTime(), nullable=True),
        sa.Column("regeneration_requested", sa.Boolean(), nullable=False),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("updated_at", sa.DateTime(), nullable=False),
        sa.UniqueConstraint("channel_id", "name", name="uq_content_profiles_channel_name"),
        sa.CheckConstraint("schedule_type IN ('interval', 'daily')", name="ck_content_profiles_schedule_type"),
    )
    op.create_index("ix_content_profiles_id", "content_profiles", ["id"])
    op.create_index("ix_content_profiles_workspace_id", "content_profiles", ["workspace_id"])
    op.create_index("ix_content_profiles_channel_id", "content_profiles", ["channel_id"])


def downgrade():
    op.drop_index("ix_content_profiles_channel_id", table_name="content_profiles")
    op.drop_index("ix_content_profiles_workspace_id", table_name="content_profiles")
    op.drop_index("ix_content_profiles_id", table_name="content_profiles")
    op.drop_table("content_profiles")
