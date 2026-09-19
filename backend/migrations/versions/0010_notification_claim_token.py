from alembic import op
import sqlalchemy as sa


revision = "0010_notification_claim_token"
down_revision = "0009_profile_scheduler_lease"
branch_labels = None
depends_on = None


def upgrade():
    op.add_column(
        "contents",
        sa.Column("approval_notification_claim_token", sa.String(length=64), nullable=True),
    )


def downgrade():
    op.drop_column("contents", "approval_notification_claim_token")
