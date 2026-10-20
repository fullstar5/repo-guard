import pytest  # pyright: ignore[reportMissingImports]
from pydantic import ValidationError  # pyright: ignore[reportMissingImports]

from app.schemas.review_job import CreateReviewJobRequest


def test_create_review_job_accepts_allowlisted_models():
    free = CreateReviewJobRequest(model_name="openrouter/free")
    nemotron = CreateReviewJobRequest(
        model_name="nvidia/nemotron-3-ultra-550b-a55b:free",
    )
    assert free.model_name == "openrouter/free"
    assert nemotron.provider == "openrouter"


def test_create_review_job_rejects_unknown_model():
    with pytest.raises(ValidationError) as exc_info:
        CreateReviewJobRequest(model_name="openai/gpt-4o")

    assert "model_name must be one of" in str(exc_info.value)


def test_agent_review_rejects_a_workflow_only_model():
    with pytest.raises(ValidationError) as exc_info:
        CreateReviewJobRequest(model_name="openrouter/free", use_agent=True)

    assert "agent model_name must be one of" in str(exc_info.value)


def test_agent_review_accepts_the_tool_model():
    request = CreateReviewJobRequest(
        model_name="nvidia/nemotron-3.5-super-vl:free",
        use_agent=True,
    )
    assert request.use_agent is True
