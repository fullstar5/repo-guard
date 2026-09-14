from datetime import datetime

from pydantic import BaseModel, ConfigDict  # pyright: ignore[reportMissingImports]



class RepositoryRead(BaseModel):
    id: int
    github_repo_id: int
    name: str
    full_name: str
    owner_login: str
    private: bool
    default_branch: str | None = None
    updated_at: datetime

    model_config = ConfigDict(from_attributes=True)



class RepositorySyncResponse(BaseModel):
    count: int
    items: list[RepositoryRead]
