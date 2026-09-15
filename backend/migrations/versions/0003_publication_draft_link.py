"""Link new publications to legacy Telegram drafts.

Revision ID: 0003_publication_draft_link
Revises: 0002_publication_state
"""
from alembic import op
import sqlalchemy as sa

revision = "0003_publication_draft_link"
down_revision = "0002_publication_state"
branch_labels = None
depends_on = None


def upgrade():
    op.add_column("publications", sa.Column("source_draft_id", sa.Integer(), nullable=True))
    op.create_index("ix_publications_source_draft_id", "publications", ["source_draft_id"])
    op.create_foreign_key(
        "fk_publications_source_draft_id",
        "publications",
        "post_drafts",
        ["source_draft_id"],
        ["id"],
        ondelete="SET NULL",
    )


def downgrade():
    op.drop_constraint("fk_publications_source_draft_id", "publications", type_="foreignkey")
    op.drop_index("ix_publications_source_draft_id", table_name="publications")
    op.drop_column("publications", "source_draft_id")
