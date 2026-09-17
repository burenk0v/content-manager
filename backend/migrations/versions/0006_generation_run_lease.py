from alembic import op
import sqlalchemy as sa

revision = "0006_generation_run_lease"
down_revision = "0005_content_profiles"
branch_labels = None
depends_on = None


def upgrade():
    op.add_column("generation_runs", sa.Column("lease_heartbeat_at", sa.DateTime(), nullable=True))
    op.create_index("ix_generation_runs_lease_heartbeat_at", "generation_runs", ["lease_heartbeat_at"])


def downgrade():
    op.drop_index("ix_generation_runs_lease_heartbeat_at", table_name="generation_runs")
    op.drop_column("generation_runs", "lease_heartbeat_at")
