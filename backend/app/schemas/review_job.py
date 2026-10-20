# define 'review job' api request and response structure

from datetime import datetime

from app.core.config import AGENT_REVIEW_MODELS, REVIEW_MODEL_ALLOWLIST
from app.schemas.review_finding import ReviewFindingRead
from pydantic import BaseModel, ConfigDict, Field, model_validator  # pyright: ignore[reportMissingImports]


class CreateReviewJobRequest(BaseModel):
    provider: str = "openrouter"
    model_name: str = "openrouter/free"
    use_agent: bool = False

    @model_validator(mode="after")
    def model_matches_review_method(self) -> "CreateReviewJobRequest":
        """Reject a model that the selected review method cannot call.

        Agent jobs may only use models that return tool calls. Workflow jobs
        use the wider manual-review allowlist.

        Returns:
            This request when the model is allowed.

        Raises:
            ValueError: The model is outside the list for ``use_agent``.
            FastAPI turns that into HTTP 422.
        """
        if self.use_agent:
            allowed = AGENT_REVIEW_MODELS
            label = "agent model_name"
        else:
            allowed = REVIEW_MODEL_ALLOWLIST
            label = "model_name"
        if self.model_name not in allowed:
            raise ValueError(f"{label} must be one of: {', '.join(allowed)}")
        return self


class ReviewJobRead(BaseModel):
    id: int
    pull_request_id: int
    status: str
    provider: str
    model_name: str
    use_agent: bool = False
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
    """Models the browser may select. default_model is the workflow model."""

    models: list[str]
    default_model: str
    agent_models: list[str]
    agent_default_model: str