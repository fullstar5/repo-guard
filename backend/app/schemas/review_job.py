# define 'review job' api request and response structure

from datetime import datetime

from pydantic import BaseModel, ConfigDict, Field, field_validator  # pyright: ignore[reportMissingImports]

from app.core.config import REVIEW_MODEL_ALLOWLIST
from app.schemas.review_finding import ReviewFindingRead



class CreateReviewJobRequest(BaseModel):
    provider: str = "openrouter"
    model_name: str = "openrouter/free"

    @field_validator("model_name")
    @classmethod
    def model_name_must_be_allowed(cls, value: str) -> str:
        """Reject model ids that are not on the manual-review allowlist.

        Args:
            value: ``model_name`` from the create-job request.

        Returns:
            The same id when it is allowed.

        Raises:
            ValueError: The id is not in ``REVIEW_MODEL_ALLOWLIST``. FastAPI
            turns that into HTTP 422.
        """
        # ADDED: reject ids that are not on the OpenRouter allowlist.
        if value not in REVIEW_MODEL_ALLOWLIST:
            allowed = ", ".join(REVIEW_MODEL_ALLOWLIST)
            raise ValueError(f"model_name must be one of: {allowed}")
        return value


class ReviewJobRead(BaseModel):
    id: int
    pull_request_id: int
    status: str
    provider: str
    model_name: str
    total_files: int
    total_chunks: int
    error_message: str | None = None
    result_summary: str | None = None
    findings: list[ReviewFindingRead] = Field(default_factory=list)
    created_at: datetime
    updated_at: datetime

    model_config = ConfigDict(from_attributes=True)


class ReviewJobListResponse(BaseModel):
    count: int
    items: list[ReviewJobRead]


class ReviewModelListResponse(BaseModel):
    """Models the browser may select. default_model is the webhook model."""

    models: list[str]
    default_model: str