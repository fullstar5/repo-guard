from datetime import datetime

from pydantic import BaseModel, ConfigDict



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

    model_config = ConfigDict(from_attributes=True)