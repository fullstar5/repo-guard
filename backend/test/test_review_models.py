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
