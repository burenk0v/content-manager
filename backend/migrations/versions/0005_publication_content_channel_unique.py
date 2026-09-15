"""Enforce one publication per content and channel.

Revision ID: 0005_publication_content_channel_unique
Revises: 0004_content_lifecycle
"""
from alembic import op
from sqlalchemy import inspect, text

revision = "0005_publication_content_channel_unique"
down_revision = "0004_content_lifecycle"
branch_labels = None
depends_on = None

INDEX_NAME = "uq_publications_content_channel"


def upgrade():
    bind = op.get_bind()
    inspector = inspect(bind)
    if "publications" not in inspector.get_table_names():
        return

    existing = {index["name"] for index in inspector.get_indexes("publications")}
    if INDEX_NAME in existing:
        return

    duplicate = bind.execute(text(
        "SELECT content_id, channel_id, COUNT(*) AS count "
        "FROM publications GROUP BY content_id, channel_id HAVING COUNT(*) > 1 LIMIT 1"
    )).first()
    if duplicate:
        raise RuntimeError(
            "Cannot create unique publication invariant: duplicate "
            f"content_id={duplicate[0]}, channel_id={duplicate[1]} exists"
        )

    op.create_index(
        INDEX_NAME,
        "publications",
        ["content_id", "channel_id"],
        unique=True,
    )


def downgrade():
    bind = op.get_bind()
    inspector = inspect(bind)
    existing = {index["name"] for index in inspector.get_indexes("publications")}
    if INDEX_NAME in existing:
        op.drop_index(INDEX_NAME, table_name="publications")
