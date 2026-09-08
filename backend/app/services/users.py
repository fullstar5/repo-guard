from sqlalchemy import select  # pyright: ignore[reportMissingImports]
from sqlalchemy.ext.asyncio import AsyncSession  # pyright: ignore[reportMissingImports]

from app.models.user import User
from app.schemas.auth import GitHubUserProfile, GitHubAccessTokenResponse


async def upsert_github_user(
    db: AsyncSession,
    github_user: GitHubUserProfile,
    token_data: GitHubAccessTokenResponse,
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
            github_access_token=token_data.access_token,
            github_token_scope=token_data.scope,
        )
        db.add(user)

    else:
        user.github_login = github_user.login
        user.email = resolved_email
        user.github_access_token = token_data.access_token
        user.github_token_scope = token_data.scope

    await db.commit()
    await db.refresh(user)

    return user