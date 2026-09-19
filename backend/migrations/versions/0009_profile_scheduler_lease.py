from alembic import op
import sqlalchemy as sa

revision = "0009_profile_scheduler_lease"
down_revision = "0008_generation_run_active_guard"
branch_labels = None
depends_on = None


def upgrade():
    op.add_column("content_profiles", sa.Column("scheduler_lease_token", sa.String(length=64), nullable=True))
    op.add_column("content_profiles", sa.Column("scheduler_lease_heartbeat_at", sa.DateTime(), nullable=True))
    op.create_index("ix_content_profiles_scheduler_lease_heartbeat", "content_profiles", ["scheduler_lease_heartbeat_at"])


def downgrade():
    op.drop_index("ix_content_profiles_scheduler_lease_heartbeat", table_name="content_profiles")
    op.drop_column("content_profiles", "scheduler_lease_heartbeat_at")
    op.drop_column("content_profiles", "scheduler_lease_token")
