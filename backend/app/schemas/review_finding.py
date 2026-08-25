from datetime import datetime

from pydantic import BaseModel, ConfigDict  # pyright: ignore[reportMissingImports]



class ReviewFindingRead(BaseModel):
    id: int
    severity: str
    summary: str
    file_path: str | None = None
    start_line: int | None = None
    end_line: int | None = None
    suggestion: str | None = None
    created_at: datetime
    updated_at: datetime
    pr_file_id: int | None = None

    model_config = ConfigDict(from_attributes=True)