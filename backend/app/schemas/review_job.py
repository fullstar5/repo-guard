# define 'review job' api request and response structure

from datetime import datetime

from pydantic import BaseModel, ConfigDict, Field  # pyright: ignore[reportMissingImports]

from app.schemas.review_finding import ReviewFindingRead



class CreateReviewJobRequest(BaseModel):
    provider: str = "openrouter"
    model_name: str = "openrouter/free"


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