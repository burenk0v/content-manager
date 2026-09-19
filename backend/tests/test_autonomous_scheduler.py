from datetime import datetime, timedelta

from src.app.db import SessionLocal
from src.app.models import ContentProfile
from src.app.services.autonomous_scheduler import claim_due_profile, recover_stale_scheduler_leases


def test_scheduler_claims_due_profile_once():
    from tests.test_autonomous_generation import create_profile

    profile_data = create_profile()
    db = SessionLocal()
    try:
        token = claim_due_profile(db, profile_data["id"])
        assert token
        profile = db.query(ContentProfile).filter(ContentProfile.id == profile_data["id"]).first()
        assert profile.scheduler_lease_token == token

        assert claim_due_profile(db, profile_data["id"]) is None
    finally:
        db.close()


def test_scheduler_recovers_stale_lease():
    from tests.test_autonomous_generation import create_profile

    profile_data = create_profile()
    db = SessionLocal()
    try:
        profile = db.query(ContentProfile).filter(ContentProfile.id == profile_data["id"]).first()
        profile.scheduler_lease_token = "stale-token"
        profile.scheduler_lease_heartbeat_at = datetime.utcnow() - timedelta(hours=2)
        profile.regeneration_requested = False
        db.commit()

        assert recover_stale_scheduler_leases(db) == 1

        db.refresh(profile)
        assert profile.scheduler_lease_token is None
        assert profile.scheduler_lease_heartbeat_at is None
        assert profile.regeneration_requested is True
    finally:
        db.close()


def test_manual_generation_cannot_bypass_scheduler_lease():
    from tests.test_autonomous_generation import create_profile
    from src.app.services.generation_service import GenerationConflict, generate_profile_content

    profile_data = create_profile()
    db = SessionLocal()
    try:
        profile = db.query(ContentProfile).filter(ContentProfile.id == profile_data["id"]).first()
        profile.scheduler_lease_token = "owned-by-scheduler"
        profile.scheduler_lease_heartbeat_at = datetime.utcnow()
        db.commit()

        try:
            generate_profile_content(db, profile.id)
        except GenerationConflict as exc:
            assert "scheduler" in str(exc).lower()
        else:
            raise AssertionError("manual generation bypassed scheduler lease")
    finally:
        db.close()
