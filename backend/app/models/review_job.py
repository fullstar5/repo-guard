from datetime import datetime
from enum import Enum as PyEnum

from sqlalchemy import (
    DateTime,
    Enum,
    ForeignKey,
    Index,
    Integer,
    String,
    Text,
    func,
    text,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.models.base import Base




class ReviewJobStatus(str, PyEnum):
    pending = "pending"
    processing = "processing"
    completed = "completed"
    failed = "failed"


class ReviewJob(Base):
    __tablename__ = "review_jobs"

    # Preserve terminal history while allowing only one active job per PR.
    __table_args__ = (
        Index(
            "uq_review_jobs_active_pull_request",
            "pull_request_id",
            unique=True,
            postgresql_where=text(
                "status IN ('pending', 'processing')"
            ),
        ),
    )

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    pull_request_id: Mapped[int] = mapped_column(
        ForeignKey("pull_requests.id"),
        nullable=False,
        index=True,
    )

    status: Mapped[ReviewJobStatus] = mapped_column(
        Enum(ReviewJobStatus, name="review_job_status"),
        nullable=False,
        default=ReviewJobStatus.pending,
    )

    provider: Mapped[str] = mapped_column(String(100), nullable=False)
    model_name: Mapped[str] = mapped_column(String(255), nullable=False)

    total_files: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    total_chunks: Mapped[int] = mapped_column(Integer, nullable=False, default=0)

    error_message: Mapped[str | None] = mapped_column(Text, nullable=True)
    result_summary: Mapped[str | None] = mapped_column(Text, nullable=True)

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

    pull_request = relationship("PullRequest")
    findings = relationship(
        "ReviewFinding",
        back_populates="review_job",
        cascade="all, delete-orphan",
    )