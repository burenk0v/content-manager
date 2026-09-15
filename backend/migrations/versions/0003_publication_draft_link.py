"""Link new publications to legacy Telegram drafts.

Revision ID: 0003_publication_draft_link
Revises: 0002_publication_state
"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy import inspect

revision = "0003_publication_draft_link"
down_revision = "0002_publication_state"
branch_labels = None
depends_on = None


def upgrade():
    bind = op.get_bind()
    inspector = inspect(bind)
    columns = {column["name"] for column in inspector.get_columns("publications")}
    if "source_draft_id" not in columns:
        op.add_column("publications", sa.Column("source_draft_id", sa.Integer(), nullable=True))

    indexes = {index["name"] for index in inspector.get_indexes("publications")}
    if "ix_publications_source_draft_id" not in indexes:
        op.create_index("ix_publications_source_draft_id", "publications", ["source_draft_id"])

    foreign_keys = {fk["name"] for fk in inspector.get_foreign_keys("publications") if fk.get("name")}
    if "fk_publications_source_draft_id" not in foreign_keys:
        op.create_foreign_key(
            "fk_publications_source_draft_id",
            "publications",
            "post_drafts",
            ["source_draft_id"],
            ["id"],
            ondelete="SET NULL",
        )


def downgrade():
    bind = op.get_bind()
    inspector = inspect(bind)
    foreign_keys = {fk["name"] for fk in inspector.get_foreign_keys("publications") if fk.get("name")}
    if "fk_publications_source_draft_id" in foreign_keys:
        op.drop_constraint("fk_publications_source_draft_id", "publications", type_="foreignkey")
    indexes = {index["name"] for index in inspector.get_indexes("publications")}
    if "ix_publications_source_draft_id" in indexes:
        op.drop_index("ix_publications_source_draft_id", table_name="publications")
    columns = {column["name"] for column in inspector.get_columns("publications")}
    if "source_draft_id" in columns:
        op.drop_column("publications", "source_draft_id")
