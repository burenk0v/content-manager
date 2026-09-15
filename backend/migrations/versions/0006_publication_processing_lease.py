"""Add a lease token to publication processing claims.

Revision ID: 0006_publication_processing_lease
Revises: 0005_publication_content_channel_unique
"""
from alembic import op
from sqlalchemy import inspect

revision = "0006_publication_processing_lease"
down_revision = "0005_publication_content_channel_unique"
branch_labels = None
depends_on = None

COLUMN_NAME = "processing_token"
INDEX_NAME = "ix_publications_processing_token"


def upgrade():
    bind = op.get_bind()
    inspector = inspect(bind)
    if "publications" not in inspector.get_table_names():
        return

    columns = {column["name"] for column in inspector.get_columns("publications")}
    if COLUMN_NAME not in columns:
        op.add_column("publications", op.f("processing_token"))

    indexes = {index["name"] for index in inspector.get_indexes("publications")}
    if INDEX_NAME not in indexes:
        op.create_index(INDEX_NAME, "publications", [COLUMN_NAME], unique=False)


def downgrade():
    bind = op.get_bind()
    inspector = inspect(bind)
    if "publications" not in inspector.get_table_names():
        return

    indexes = {index["name"] for index in inspector.get_indexes("publications")}
    if INDEX_NAME in indexes:
        op.drop_index(INDEX_NAME, table_name="publications")

    columns = {column["name"] for column in inspector.get_columns("publications")}
    if COLUMN_NAME in columns:
        op.drop_column("publications", COLUMN_NAME)
