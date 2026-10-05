from datetime import datetime

from app.models.base import Base
from sqlalchemy import (  # pyright: ignore[reportMissingImports]
    BigInteger,
    DateTime,
    String,
    Text,
    func,
)
from sqlalchemy.orm import (  # pyright: ignore[reportMissingImports]
    Mapped,
    mapped_column,
    relationship,
)


class User(Base):
    __tablename__ = "users"

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    github_id: Mapped[int] = mapped_column(BigInteger, unique=True, index=True)
    github_login: Mapped[str] = mapped_column(String(255), unique=True, index=True)
    email: Mapped[str | None] = mapped_column(String(255), nullable=True)

    # token
    github_access_token: Mapped[str | None] = mapped_column(Text, nullable=True)
    github_refresh_token: Mapped[str | None] = mapped_column(Text, nullable=True)
    github_token_scope: Mapped[str | None] = mapped_column(String(255), nullable=True)
    github_access_token_expires_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True),
        nullable=True,
    )
    github_refresh_token_expires_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True),
        nullable=True,
    )

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
    
    repositories = relationship("Repository", back_populates="user")
