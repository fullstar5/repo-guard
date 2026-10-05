from datetime import datetime, timedelta, timezone

from app.models.user import User
from app.schemas.auth import GitHubAccessTokenResponse, GitHubUserProfile
from sqlalchemy import select  # pyright: ignore[reportMissingImports]
from sqlalchemy.ext.asyncio import AsyncSession  # pyright: ignore[reportMissingImports]


def apply_github_token(
    user: User,
    token_data: GitHubAccessTokenResponse,
    *,
    now: datetime | None = None,
) -> None:
    """Store a GitHub user-token response and its expiration timestamps.

    GitHub rotates refresh tokens. A refresh response must therefore replace
    both tokens atomically on the same user row.

    Args:
        user: User row to update.
        token_data: OAuth authorization-code or refresh response.
        now: UTC clock used to calculate absolute expiration timestamps.

    Returns:
        None.
    """
    current = now or datetime.now(timezone.utc)
    user.github_access_token = token_data.access_token
    user.github_token_scope = token_data.scope or None
    user.github_access_token_expires_at = (
        current + timedelta(seconds=token_data.expires_in)
        if token_data.expires_in is not None
        else None
    )

    if token_data.refresh_token:
        user.github_refresh_token = token_data.refresh_token
        user.github_refresh_token_expires_at = (
            current + timedelta(seconds=token_data.refresh_token_expires_in)
            if token_data.refresh_token_expires_in is not None
            else None
        )


async def upsert_github_user(
    db: AsyncSession,
    github_user: GitHubUserProfile,
    token_data: GitHubAccessTokenResponse,
    email: str | None,
) -> User:
    """Insert or update the local user for a GitHub account.

    Args:
        db: Open async session.
        github_user: Profile from ``GET /user``.
        token_data: OAuth token response, including scope.
        email: Verified primary email, or None when GitHub did not provide one.

    Returns:
        The committed user row.
    """
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

    apply_github_token(user, token_data)

    await db.commit()
    await db.refresh(user)

    return user