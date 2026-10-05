from collections.abc import Awaitable, Callable
from datetime import datetime, timedelta, timezone
from typing import TypeVar

import httpx  # pyright: ignore[reportMissingImports]
from app.core.database import AsyncSessionLocal
from app.models.user import User
from app.services.github_oauth import (
    GitHubTokenRefreshError,
    refresh_github_access_token,
)
from app.services.users import apply_github_token
from sqlalchemy import select  # pyright: ignore[reportMissingImports]

ResultT = TypeVar("ResultT")
_REFRESH_SKEW = timedelta(minutes=10)


class GitHubTokenUnavailable(RuntimeError):
    """The user must authorize GitHub again before API calls can continue."""


def _token_is_fresh(user: User, now: datetime) -> bool:
    """Return whether the stored access token can be used without refreshing."""
    if not user.github_access_token:
        return False
    expires_at = user.github_access_token_expires_at
    if expires_at is None:
        # GitHub may issue non-expiring tokens. Legacy rows also reach this
        # branch and are refreshed only if GitHub rejects them with 401.
        return True
    return expires_at > now + _REFRESH_SKEW


async def get_valid_github_access_token(
    user_id: int,
    http_client: httpx.AsyncClient,
    *,
    force_refresh: bool = False,
    failed_access_token: str | None = None,
) -> str:
    """Return a usable GitHub user token, refreshing it when necessary.

    The user row remains locked during refresh because GitHub rotates refresh
    tokens. When two requests receive 401 for the same token, the second one
    observes the first one's replacement instead of rotating it again.

    Args:
        user_id: Local user whose GitHub credentials should be used.
        http_client: Client used to call GitHub's OAuth endpoint.
        force_refresh: Refresh even when the stored expiry has not elapsed.
        failed_access_token: Token that produced 401. If another task already
            replaced it, the replacement is returned without another refresh.

    Returns:
        A current GitHub access token.

    Raises:
        GitHubTokenUnavailable: The user or refresh credential is unavailable.
        httpx.HTTPError: A transient refresh request failed.
    """
    async with AsyncSessionLocal() as db:
        result = await db.execute(
            select(User).where(User.id == user_id).with_for_update()
        )
        user = result.scalar_one_or_none()
        if user is None:
            raise GitHubTokenUnavailable(f"User {user_id} was not found")

        now = datetime.now(timezone.utc)
        current_access_token = user.github_access_token

        if (
            failed_access_token is not None
            and current_access_token
            and current_access_token != failed_access_token
        ):
            await db.rollback()
            return current_access_token

        if not force_refresh and _token_is_fresh(user, now):
            assert current_access_token is not None
            await db.rollback()
            return current_access_token

        if not user.github_refresh_token:
            raise GitHubTokenUnavailable(
                "GitHub authorization expired. Log in again to reconnect it."
            )

        refresh_expires_at = user.github_refresh_token_expires_at
        if refresh_expires_at is not None and refresh_expires_at <= now:
            raise GitHubTokenUnavailable(
                "GitHub refresh token expired. Log in again to reconnect it."
            )

        try:
            token_data = await refresh_github_access_token(
                http_client,
                user.github_refresh_token,
            )
        except GitHubTokenRefreshError as exc:
            raise GitHubTokenUnavailable(
                "GitHub authorization can no longer be refreshed. Log in again."
            ) from exc

        apply_github_token(user, token_data, now=now)
        new_access_token = user.github_access_token
        if not new_access_token:
            raise GitHubTokenUnavailable(
                "GitHub refresh response did not contain an access token."
            )

        await db.commit()
        return new_access_token


class GitHubTokenSession:
    """Reuse one user's token across several GitHub calls in one operation."""

    def __init__(
        self,
        user_id: int,
        http_client: httpx.AsyncClient,
    ) -> None:
        self.user_id = user_id
        self.http_client = http_client
        self.access_token: str | None = None

    async def run(
        self,
        operation: Callable[[str], Awaitable[ResultT]],
    ) -> ResultT:
        """Run a GitHub operation and refresh once after a 401 response."""
        if self.access_token is None:
            self.access_token = await get_valid_github_access_token(
                self.user_id,
                self.http_client,
            )

        failed_token = self.access_token
        try:
            return await operation(failed_token)
        except httpx.HTTPStatusError as exc:
            if exc.response.status_code != 401:
                raise

        self.access_token = await get_valid_github_access_token(
            self.user_id,
            self.http_client,
            force_refresh=True,
            failed_access_token=failed_token,
        )
        try:
            return await operation(self.access_token)
        except httpx.HTTPStatusError as exc:
            if exc.response.status_code == 401:
                raise GitHubTokenUnavailable(
                    "GitHub rejected the refreshed authorization. "
                    "Log in again to reconnect it."
                ) from exc
            raise


async def call_with_github_token(
    user_id: int,
    http_client: httpx.AsyncClient,
    operation: Callable[[str], Awaitable[ResultT]],
) -> ResultT:
    """Run one GitHub operation with proactive refresh and one 401 retry."""
    return await GitHubTokenSession(user_id, http_client).run(operation)
