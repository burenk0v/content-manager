import uuid

from tests.test_foundation_api import HEADERS, client


def create_profile(*, schedule_value="60"):
    suffix = uuid.uuid4().hex[:8]
    workspace = client.post(
        "/content/workspaces",
        json={"name": f"Profile {suffix}", "slug": f"profile-{suffix}"},
        headers=HEADERS,
    )
    assert workspace.status_code == 201
    workspace_id = workspace.json()["id"]
    channel = client.post(
        "/content/channels",
        json={
            "workspace_id": workspace_id,
            "platform": "telegram",
            "external_id": f"@profile_{suffix}",
            "name": "Profile channel",
        },
        headers=HEADERS,
    )
    assert channel.status_code == 201
    response = client.post(
        "/content/profiles",
        json={
            "workspace_id": workspace_id,
            "channel_id": channel.json()["id"],
            "name": "Autonomous profile",
            "schedule_type": "interval",
            "schedule_value": schedule_value,
            "timezone": "UTC",
        },
        headers=HEADERS,
    )
    assert response.status_code == 201
    return response.json()


def test_profile_claim_is_single_use_until_next_schedule():
    profile = create_profile()
    first = client.post(f"/content/profiles/{profile['id']}/claim", headers=HEADERS)
    assert first.status_code == 200
    assert first.json()["last_run"] is not None

    second = client.post(f"/content/profiles/{profile['id']}/claim", headers=HEADERS)
    assert second.status_code == 409


def test_profile_regeneration_request_can_be_claimed_immediately():
    profile = create_profile(schedule_value="99999")
    request = client.post(f"/content/profiles/{profile['id']}/regenerate", headers=HEADERS)
    assert request.status_code == 200

    claim = client.post(f"/content/profiles/{profile['id']}/claim", headers=HEADERS)
    assert claim.status_code == 200
    assert claim.json()["regeneration_requested"] is False
