"""Add database invariants and indexes for concurrent operations."""

from alembic import op

revision = "0004_persistence_guards"
down_revision = "0003_content_variants"
branch_labels = None
depends_on = None


def upgrade():
    op.create_check_constraint(
        "ck_content_versions_version_positive",
        "content_versions",
        "version > 0",
    )
    op.create_check_constraint(
        "ck_contents_status_valid",
        "contents",
        "status IN ('draft', 'review', 'approved', 'scheduled', 'publishing', 'published', 'failed', 'archived')",
    )
    op.create_check_constraint(
        "ck_publications_status_valid",
        "publications",
        "status IN ('scheduled', 'processing', 'published', 'failed')",
    )
    op.create_check_constraint(
        "ck_publications_attempt_count_nonnegative",
        "publications",
        "attempt_count >= 0",
    )
    op.create_check_constraint(
        "ck_publication_operations_status_valid",
        "publication_operations",
        "status IN ('pending', 'processing', 'succeeded', 'failed', 'unknown')",
    )
    op.create_check_constraint(
        "ck_publication_operations_attempt_count_nonnegative",
        "publication_operations",
        "attempt_count >= 0",
    )
    op.create_check_constraint(
        "ck_generation_runs_status_valid",
        "generation_runs",
        "status IN ('running', 'succeeded', 'failed')",
    )
    op.create_check_constraint(
        "ck_content_variants_version_positive",
        "content_variants",
        "version > 0",
    )

    op.create_index(
        "ix_publications_ready_queue",
        "publications",
        ["status", "next_attempt_at", "scheduled_at", "id"],
    )
    op.create_index(
        "ix_publications_stale_processing",
        "publications",
        ["status", "lease_heartbeat_at", "processing_started_at", "id"],
    )


def downgrade():
    op.drop_index("ix_publications_stale_processing", table_name="publications")
    op.drop_index("ix_publications_ready_queue", table_name="publications")

    op.drop_constraint("ck_content_variants_version_positive", "content_variants", type_="check")
    op.drop_constraint("ck_generation_runs_status_valid", "generation_runs", type_="check")
    op.drop_constraint("ck_publication_operations_attempt_count_nonnegative", "publication_operations", type_="check")
    op.drop_constraint("ck_publication_operations_status_valid", "publication_operations", type_="check")
    op.drop_constraint("ck_publications_attempt_count_nonnegative", "publications", type_="check")
    op.drop_constraint("ck_publications_status_valid", "publications", type_="check")
    op.drop_constraint("ck_contents_status_valid", "contents", type_="check")
    op.drop_constraint("ck_content_versions_version_positive", "content_versions", type_="check")
