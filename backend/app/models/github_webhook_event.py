from datetime import datetime

from sqlalchemy import BigInteger, DateTime, Integer, String, func
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base



class GitHubWebhookEvent(Base):
    """Persist accepted GitHub deliveries for replay protection and auditing."""

    __tablename__ = "github_webhook_events"

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    delivery_id: Mapped[str] = mapped_column(
        String(255),
        nullable=False,
        unique=True,
    )
    event_name: Mapped[str] = mapped_column(String(100), nullable=False)
    action: Mapped[str | None] = mapped_column(String(100), nullable=True)
    github_repo_id: Mapped[int | None] = mapped_column(BigInteger, nullable=True)
    pull_request_number: Mapped[int | None] = mapped_column(Integer, nullable=True)

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