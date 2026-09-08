# define AI provider interface


from abc import ABC, abstractmethod

from typing import Literal

from pydantic import BaseModel, Field  # pyright: ignore[reportMissingImports]



class ReviewFindingDraft(BaseModel):
    severity: Literal["low", "medium", "high", "critical"]
    summary: str
    file_path: str | None = None
    start_line: int | None = None
    end_line: int | None = None
    suggestion: str | None = None


class ReviewResult(BaseModel):
    summary: str
    findings: list[ReviewFindingDraft] = Field(default_factory=list)


class ReviewProvider(ABC):
    @abstractmethod
    async def review_content(self, content: str) -> ReviewResult:
        """Review one prepared input payload and return model output."""
        raise NotImplementedError