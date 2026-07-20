# define 'review job' api request and response structure

from datetime import datetime

from pydantic import BaseModel, ConfigDict




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
    created_at: datetime
    updated_at: datetime

    model_config = ConfigDict(from_attributes=True)