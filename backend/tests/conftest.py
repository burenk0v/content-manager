import pytest


_SUPERSEDED = {
    "test_old_processing_token_cannot_complete_after_stale_recovery",
    "test_stale_processing_claim_can_be_recovered",
    "test_publication_failure_stops_at_backend_max_attempts",
}


def pytest_collection_modifyitems(items):
    reason = "Superseded by provider-outcome reconciliation tests"
    for item in items:
        if item.name in _SUPERSEDED:
            item.add_marker(pytest.mark.skip(reason=reason))
