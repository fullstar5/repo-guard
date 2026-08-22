from datetime import datetime

from pydantic import BaseModel, ConfigDict  # pyright: ignore[reportMissingImports]



class PullRequestRead(BaseModel):
    id: int
    github_pr_id: int
    number: int
    title: str
    state: str
    author_login: str | None = None
    html_url: str
    base_branch: str
    head_branch: str
    is_draft: bool
    github_created_at: datetime
    github_updated_at: datetime
    github_closed_at: datetime | None = None
    github_merged_at: datetime | None = None
    model_config = ConfigDict(from_attributes=True)


class PullRequestSyncResponse(BaseModel):
    count: int
    items: list[PullRequestRead]