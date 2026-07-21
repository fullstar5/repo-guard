from datetime import datetime
from enum import Enum as PyEnum

from sqlalchemy import DateTime, Enum, ForeignKey, Integer, String, Text, func
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.models.base import Base



class ReviewFindingSeverity(str, PyEnum):
    low = "low"
    medium = "medium"
    high = "high"
    critical = "critical"


class ReviewFinding(Base):
    __tablename__ = "review_findings"

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)

    review_job_id: Mapped[int] = mapped_column(
        ForeignKey("review_jobs.id"),
        nullable=False,
        index=True,
    )

    pr_file_id: Mapped[int | None] = mapped_column(
        ForeignKey("pull_request_files.id"),
        nullable=True,
        index=True,
    )

    severity: Mapped[ReviewFindingSeverity] = mapped_column(
        Enum(ReviewFindingSeverity, name="review_finding_severity"),
        nullable=False,
    )

    summary: Mapped[str] = mapped_column(String(600), nullable=False)
    file_path: Mapped[str | None] = mapped_column(String(500), nullable=True)
    start_line: Mapped[int | None] = mapped_column(Integer, nullable=True)
    end_line: Mapped[int | None] = mapped_column(Integer, nullable=True)
    suggestion: Mapped[str | None] = mapped_column(Text, nullable=True)

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        nullable=False,
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        onupdate=func.now(),
        nullable=False,
    )

    review_job = relationship("ReviewJob", back_populates="findings")
    pr_file = relationship("PRFile")

