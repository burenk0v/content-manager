from alembic import op
import sqlalchemy as sa

revision = "0008_generation_run_active_guard"
down_revision = "0007_generation_run_lease"
branch_labels = None
depends_on = None


def upgrade():
    op.create_index(
        "uq_generation_runs_active_content",
        "generation_runs",
        ["content_id"],
        unique=True,
        postgresql_where=sa.text("status = 'running'"),
        sqlite_where=sa.text("status = 'running'"),
    )


def downgrade():
    op.drop_index("uq_generation_runs_active_content", table_name="generation_runs")
