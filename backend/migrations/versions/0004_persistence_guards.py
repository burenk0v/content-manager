"""Add database invariants and indexes for concurrent operations."""

from alembic import op

revision = "0004_persistence_guards"
down_revision = "0003_content_variants"
branch_labels = None
depends_on = None


def upgrade():
    with op.batch_alter_table("content_versions", recreate="auto") as batch_op:
        batch_op.create_check_constraint(
            "ck_content_versions_version_positive",
            "version > 0",
        )

    with op.batch_alter_table("contents", recreate="auto") as batch_op:
        batch_op.create_check_constraint(
            "ck_contents_status_valid",
            "status IN ('draft', 'review', 'approved', 'scheduled', 'publishing', 'published', 'failed', 'archived')",
        )

    with op.batch_alter_table("publications", recreate="auto") as batch_op:
        batch_op.create_check_constraint(
            "ck_publications_status_valid",
            "status IN ('scheduled', 'processing', 'published', 'failed')",
        )
        batch_op.create_check_constraint(
            "ck_publications_attempt_count_nonnegative",
            "attempt_count >= 0",
        )

    with op.batch_alter_table("publication_operations", recreate="auto") as batch_op:
        batch_op.create_check_constraint(
            "ck_publication_operations_status_valid",
            "status IN ('pending', 'processing', 'succeeded', 'failed', 'unknown')",
        )
        batch_op.create_check_constraint(
            "ck_publication_operations_attempt_count_nonnegative",
            "attempt_count >= 0",
        )

    with op.batch_alter_table("generation_runs", recreate="auto") as batch_op:
        batch_op.create_check_constraint(
            "ck_generation_runs_status_valid",
            "status IN ('running', 'succeeded', 'failed')",
        )

    with op.batch_alter_table("content_variants", recreate="auto") as batch_op:
        batch_op.create_check_constraint(
            "ck_content_variants_version_positive",
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

    with op.batch_alter_table("content_variants", recreate="auto") as batch_op:
        batch_op.drop_constraint("ck_content_variants_version_positive", type_="check")

    with op.batch_alter_table("generation_runs", recreate="auto") as batch_op:
        batch_op.drop_constraint("ck_generation_runs_status_valid", type_="check")

    with op.batch_alter_table("publication_operations", recreate="auto") as batch_op:
        batch_op.drop_constraint("ck_publication_operations_attempt_count_nonnegative", type_="check")
        batch_op.drop_constraint("ck_publication_operations_status_valid", type_="check")

    with op.batch_alter_table("publications", recreate="auto") as batch_op:
        batch_op.drop_constraint("ck_publications_attempt_count_nonnegative", type_="check")
        batch_op.drop_constraint("ck_publications_status_valid", type_="check")

    with op.batch_alter_table("contents", recreate="auto") as batch_op:
        batch_op.drop_constraint("ck_contents_status_valid", type_="check")

    with op.batch_alter_table("content_versions", recreate="auto") as batch_op:
        batch_op.drop_constraint("ck_content_versions_version_positive", type_="check")
