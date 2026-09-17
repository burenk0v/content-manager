"""persist content profile linkage and approval notification state

Revision ID: 0006_approval_notifications
Revises: 0005_content_profiles
"""

from alembic import op
import sqlalchemy as sa

revision = "0006_approval_notifications"
down_revision = "0005_content_profiles"
branch_labels = None
depends_on = None


def upgrade():
    with op.batch_alter_table("contents", recreate="auto") as batch_op:
        batch_op.add_column(sa.Column("profile_id", sa.Integer(), nullable=True))
        batch_op.add_column(sa.Column("approval_notification_claimed_at", sa.DateTime(), nullable=True))
        batch_op.add_column(sa.Column("approval_notification_sent_at", sa.DateTime(), nullable=True))
        batch_op.create_index("ix_contents_profile_id", ["profile_id"])
        batch_op.create_index("ix_contents_approval_notification_claimed_at", ["approval_notification_claimed_at"])
        batch_op.create_index("ix_contents_approval_notification_sent_at", ["approval_notification_sent_at"])
        batch_op.create_foreign_key("fk_contents_profile_id", "content_profiles", ["profile_id"], ["id"], ondelete="SET NULL")


def downgrade():
    with op.batch_alter_table("contents", recreate="auto") as batch_op:
        batch_op.drop_constraint("fk_contents_profile_id", type_="foreignkey")
        batch_op.drop_index("ix_contents_approval_notification_sent_at")
        batch_op.drop_index("ix_contents_approval_notification_claimed_at")
        batch_op.drop_index("ix_contents_profile_id")
        batch_op.drop_column("approval_notification_sent_at")
        batch_op.drop_column("approval_notification_claimed_at")
        batch_op.drop_column("profile_id")
