import os

os.environ["SERVICE_ACCOUNT_TOKEN"] = "test-token"

from src.app.ai_generation import GenerationError, GenerationRequest
from src.app.domain.content_state_machine import transition


def test_generation_request_is_explicit_and_immutable():
    request = GenerationRequest(prompt="Write a post", system_message="Be concise", model="test-model")
    assert request.prompt == "Write a post"
    assert request.system_message == "Be concise"
    assert request.model == "test-model"


def test_generation_error_is_provider_safe():
    error = GenerationError("provider unavailable")
    assert str(error) == "provider unavailable"


def test_regeneration_target_is_draft_for_approved_content():
    assert transition("approved", "draft") == "draft"
    assert transition("scheduled", "draft") == "draft"
    assert transition("review", "draft") == "draft"
