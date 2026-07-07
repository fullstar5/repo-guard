from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.user import User
from app.schemas.auth import GitHubUserProfile


async def upsert_github_user(
    db: AsyncSession,
    github_user: GitHubUserProfile,
    email: str | None,
) -> User:
    result = await db.execute(
        select(User).where(User.github_id == github_user.id)
    )
    user = result.scalar_one_or_none()

    resolved_email = email or github_user.email

    if user is None:
        user = User(
            github_id=github_user.id,
            github_login=github_user.login,
            email=resolved_email,
        )
        db.add(user)

    else:
        user.github_login = github_user.login
        user.email = resolved_email

    await db.commit()
    await db.refresh(user)

    return user