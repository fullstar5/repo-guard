from pydantic import BaseModel, ConfigDict



class PullRequestFileRead(BaseModel):
    id: int
    filename: str
    previous_filename: str | None = None
    status: str
    sha: str | None = None
    additions: int
    deletions: int
    changes: int
    blob_url: str | None = None
    raw_url: str | None = None
    contents_url: str | None = None
    patch: str | None = None

    model_config = ConfigDict(from_attributes=True)


class PullRequestFileSyncResponse(BaseModel):
    count: int
    items: list[PullRequestFileRead]
