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

    inspector = inspect(bind)
    indexes = {index["name"] for index in inspector.get_indexes("publications")}
    if "ix_publications_source_draft_id" not in indexes:
        op.create_index("ix_publications_source_draft_id", "publications", ["source_draft_id"])

    inspector = inspect(bind)
    has_source_draft_fk = any(
        fk.get("constrained_columns") == ["source_draft_id"] and fk.get("referred_table") == "post_drafts"
        for fk in inspector.get_foreign_keys("publications")
    )
    if bind.dialect.name != "sqlite" and not has_source_draft_fk:
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
    if bind.dialect.name != "sqlite":
        named = next(
            (fk.get("name") for fk in inspector.get_foreign_keys("publications")
             if fk.get("constrained_columns") == ["source_draft_id"] and fk.get("referred_table") == "post_drafts"),
            None,
        )
        if named:
            op.drop_constraint(named, "publications", type_="foreignkey")
    indexes = {index["name"] for index in inspector.get_indexes("publications")}
    if "ix_publications_source_draft_id" in indexes:
        op.drop_index("ix_publications_source_draft_id", table_name="publications")
    columns = {column["name"] for column in inspector.get_columns("publications")}
    if "source_draft_id" in columns:
        op.drop_column("publications", "source_draft_id")
