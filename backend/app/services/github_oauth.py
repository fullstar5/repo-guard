from urllib.parse import urlencode

import httpx  # pyright: ignore[reportMissingImports]
from fastapi import HTTPException, status  # pyright: ignore[reportMissingImports]

from app.core.config import get_settings
from app.schemas.auth import GitHubAccessTokenResponse, GitHubEmail, GitHubUserProfile

settings = get_settings()

GITHUB_API_HEADERS = {
    "Accept": "application/vnd.github+json",
    "X-GitHub-Api-Version": "2026-03-10",
}


def build_github_authorize_url(state: str) -> str:
    """Build the GitHub OAuth authorize URL.

    Args:
        state: Random value stored in the login cookie and checked on callback.

    Returns:
        The full ``https://github.com/login/oauth/authorize`` URL.
    """
    params = {
        "client_id": settings.github_client_id,
        "redirect_uri": settings.github_redirect_uri,
        "scope": settings.github_oauth_scope,
        "state": state,
    }
    return f"https://github.com/login/oauth/authorize?{urlencode(params)}"


async def exchange_code_for_access_token(
    http_client: httpx.AsyncClient,
    code: str,
) -> GitHubAccessTokenResponse:
    """Exchange an OAuth code for a GitHub access token.

    Args:
        http_client: Shared async HTTP client.
        code: Authorization code from the callback query string.

    Returns:
        The token payload, including scope.

    Raises:
        HTTPException: 400 when GitHub returns an OAuth error body.
        httpx.HTTPStatusError: The token endpoint returned a non-2xx status.
    """
    response = await http_client.post(
        "https://github.com/login/oauth/access_token",
        headers={"Accept": "application/json"},
        data={
            "client_id": settings.github_client_id,
            "client_secret": settings.github_client_secret,
            "code": code,
            "redirect_uri": settings.github_redirect_uri,
        },
    )
    response.raise_for_status()

    payload = response.json()

    if "error" in payload:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=payload.get("error_description", payload["error"]),
        )

    return GitHubAccessTokenResponse.model_validate(payload)


async def fetch_github_user(
    http_client: httpx.AsyncClient,
    access_token: str,
) -> GitHubUserProfile:
    """Load the GitHub profile for an access token.

    Args:
        http_client: Shared async HTTP client.
        access_token: GitHub OAuth token.

    Returns:
        The validated ``GET /user`` profile.
    """
    response = await http_client.get(
        "https://api.github.com/user",
        headers={
            **GITHUB_API_HEADERS,
            "Authorization": f"Bearer {access_token}",
        },
    )
    response.raise_for_status()
    return GitHubUserProfile.model_validate(response.json())


async def fetch_primary_email(
    http_client: httpx.AsyncClient,
    access_token: str,
) -> str | None:
    """Load a verified email address for the GitHub user.

    Args:
        http_client: Shared async HTTP client.
        access_token: GitHub OAuth token.

    Returns:
        The primary verified email, otherwise any verified email.
        None when the token cannot read emails or none are verified.
    """
    response = await http_client.get(
        "https://api.github.com/user/emails",
        headers={
            **GITHUB_API_HEADERS,
            "Authorization": f"Bearer {access_token}",
        },
    )

    # Some GitHub accounts/tokens can't access the email endpoint even though
    # the basic /user profile succeeds. Treat email as optional instead of
    # failing the whole OAuth callback.
    if response.status_code == status.HTTP_403_FORBIDDEN:
        return None

    response.raise_for_status()

    emails = [GitHubEmail.model_validate(item) for item in response.json()]

    primary_verified = next(
        (item.email for item in emails if item.primary and item.verified),
        None,
    )
    if primary_verified:
        return primary_verified

    return next((item.email for item in emails if item.verified), None)