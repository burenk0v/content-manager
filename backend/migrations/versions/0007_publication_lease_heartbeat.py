"""Add heartbeat timestamp for active publication leases.

Revision ID: 0007_publication_lease_heartbeat
Revises: 0006_publication_processing_lease
"""
import sqlalchemy as sa
from alembic import op
from sqlalchemy import inspect

revision = "0007_publication_lease_heartbeat"
down_revision = "0006_publication_processing_lease"
branch_labels = None
depends_on = None

COLUMN_NAME = "lease_heartbeat_at"
INDEX_NAME = "ix_publications_lease_heartbeat_at"


def upgrade():
    bind = op.get_bind()
    inspector = inspect(bind)
    if "publications" not in inspector.get_table_names():
        return
    columns = {column["name"] for column in inspector.get_columns("publications")}
    if COLUMN_NAME not in columns:
        op.add_column("publications", sa.Column(COLUMN_NAME, sa.DateTime(), nullable=True))
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
