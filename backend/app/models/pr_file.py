from datetime import datetime

from app.models.base import Base
from sqlalchemy import (  # pyright: ignore[reportMissingImports]
    DateTime,
    ForeignKey,
    Integer,
    String,
    Text,
    UniqueConstraint,
    func,
)
from sqlalchemy.orm import (  # pyright: ignore[reportMissingImports]
    Mapped,
    mapped_column,
    relationship,
)


class PRFile(Base):
    __tablename__ = "pull_request_files"
    __table_args__ = (
        UniqueConstraint(
            "pull_request_id",
            "filename",
            name="uq_pull_request_files_pr_filename",
        ),
    )

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    pull_request_id: Mapped[int] = mapped_column(
        ForeignKey("pull_requests.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )

    filename: Mapped[str] = mapped_column(String(500), nullable=False)
    previous_filename: Mapped[str | None] = mapped_column(String(500), nullable=True)

    status: Mapped[str] = mapped_column(String(50), nullable=False)
    sha: Mapped[str | None] = mapped_column(String(255), nullable=True)

    additions: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    deletions: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    changes: Mapped[int] = mapped_column(Integer, nullable=False, default=0)

    blob_url: Mapped[str | None] = mapped_column(String(1000), nullable=True)
    raw_url: Mapped[str | None] = mapped_column(String(1000), nullable=True)
    contents_url: Mapped[str | None] = mapped_column(String(1000), nullable=True)

    patch: Mapped[str | None] = mapped_column(Text, nullable=True)
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
    pull_request = relationship("PullRequest", back_populates="files")