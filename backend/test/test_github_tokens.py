import asyncio
from datetime import datetime, timedelta, timezone
from unittest.mock import AsyncMock, patch
from urllib.parse import parse_qs

import httpx  # pyright: ignore[reportMissingImports]
from app.models.user import User
from app.schemas.auth import GitHubAccessTokenResponse
from app.services.github_oauth import refresh_github_access_token
from app.services.github_tokens import GitHubTokenSession
from app.services.users import apply_github_token


def test_apply_github_token_stores_rotated_pair_and_expirations():
    now = datetime(2026, 10, 5, tzinfo=timezone.utc)
    user = User(
        github_id=1,
        github_login="octocat",
        email=None,
    )
    token_data = GitHubAccessTokenResponse(
        access_token="access-new",
        token_type="bearer",
        expires_in=8 * 60 * 60,
        refresh_token="refresh-new",
        refresh_token_expires_in=180 * 24 * 60 * 60,
    )

    apply_github_token(user, token_data, now=now)

    assert user.github_access_token == "access-new"
    assert user.github_refresh_token == "refresh-new"
    assert user.github_access_token_expires_at == now + timedelta(hours=8)
    assert user.github_refresh_token_expires_at == now + timedelta(days=180)


def test_refresh_github_access_token_posts_refresh_grant():
    def handler(request: httpx.Request) -> httpx.Response:
        assert request.url == "https://github.com/login/oauth/access_token"
        form = parse_qs(request.content.decode())
        assert form["grant_type"] == ["refresh_token"]
        assert form["refresh_token"] == ["refresh-old"]
        return httpx.Response(
            200,
            json={
                "access_token": "access-new",
                "token_type": "bearer",
                "expires_in": 28800,
                "refresh_token": "refresh-new",
                "refresh_token_expires_in": 15897600,
            },
        )

    async def run() -> GitHubAccessTokenResponse:
        async with httpx.AsyncClient(
            transport=httpx.MockTransport(handler)
        ) as http_client:
            return await refresh_github_access_token(
                http_client,
                "refresh-old",
            )

    result = asyncio.run(run())

    assert result.access_token == "access-new"
    assert result.refresh_token == "refresh-new"


def test_token_session_refreshes_once_and_retries_after_401():
    request = httpx.Request("GET", "https://api.github.com/user/repos")
    unauthorized = httpx.HTTPStatusError(
        "401 Unauthorized",
        request=request,
        response=httpx.Response(401, request=request),
    )
    used_tokens: list[str] = []

    async def operation(token: str) -> str:
        used_tokens.append(token)
        if token == "access-old":
            raise unauthorized
        return "ok"

    async def run() -> str:
        async with httpx.AsyncClient() as http_client:
            session = GitHubTokenSession(1, http_client)
            with patch(
                "app.services.github_tokens.get_valid_github_access_token",
                new=AsyncMock(side_effect=["access-old", "access-new"]),
            ) as get_token:
                result = await session.run(operation)

            assert get_token.await_count == 2
            second_call = get_token.await_args_list[1]
            assert second_call.kwargs["force_refresh"] is True
            assert second_call.kwargs["failed_access_token"] == "access-old"
            return result

    assert asyncio.run(run()) == "ok"
    assert used_tokens == ["access-old", "access-new"]
