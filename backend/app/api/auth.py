from secrets import token_urlsafe

import httpx  # pyright: ignore[reportMissingImports]

from fastapi import APIRouter, Depends, HTTPException, Request, Response, status  # pyright: ignore[reportMissingImports]
from fastapi.responses import RedirectResponse  # pyright: ignore[reportMissingImports]
from sqlalchemy.ext.asyncio import AsyncSession  # pyright: ignore[reportMissingImports]

from app.api.deps import get_current_user, get_db
from app.api.rate_limit_deps import limit_oauth_requests
from app.core.config import get_settings
from app.models.user import User
from app.schemas.auth import AuthUserRead, GitHubOAuthCallbackResponse
from app.services.auth_token import build_auth_response
from app.services.github_oauth import (
    build_github_authorize_url,
    exchange_code_for_access_token,
    fetch_github_user,
    fetch_primary_email,
)
from app.services.users import upsert_github_user



router = APIRouter(prefix="/auth", tags=["auth"])
settings = get_settings()

@router.get(
    "/github/login",
    dependencies=[Depends(limit_oauth_requests)],
)
async def github_login() -> RedirectResponse:
    """Start GitHub OAuth by redirecting the browser to GitHub.

    Returns:
        A 302 redirect to GitHub's authorize URL. Sets a short-lived httpOnly
        state cookie used to check the callback.
    """
    state = token_urlsafe(32)
    authorize_url = build_github_authorize_url(state)

    response = RedirectResponse(url=authorize_url, status_code=status.HTTP_302_FOUND)
    response.set_cookie(
        key=settings.oauth_state_cookie_name,
        value=state,
        max_age=600,
        httponly=True,
        secure=settings.cookie_secure,
        samesite="lax",
        path="/",
    )
    return response


@router.get(
    "/github/callback",
    dependencies=[Depends(limit_oauth_requests)],
)
async def github_callback(
    code: str,
    state: str,
    request: Request,
    db: AsyncSession = Depends(get_db),
):
    """Finish GitHub OAuth and set the session cookie.

    Args:
        code: Authorization code from GitHub.
        state: State query value that must match the login cookie.
        request: Incoming request, used for the state cookie and HTTP client.
        db: Request-scoped async session.

    Returns:
        A 302 redirect to the frontend with the access-token cookie set.

    Raises:
        HTTPException: 400 when the OAuth state does not match.
    """
    saved_state = request.cookies.get(settings.oauth_state_cookie_name)
    if not saved_state or saved_state != state:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Invalid OAuth state",
        )
    http_client: httpx.AsyncClient = request.app.state.http_client
    token_response = await exchange_code_for_access_token(http_client, code)
    github_user = await fetch_github_user(http_client, token_response.access_token)
    primary_email = await fetch_primary_email(http_client, token_response.access_token)
    user = await upsert_github_user(
        db=db,
        github_user=github_user,
        token_data=token_response,
        email=primary_email,
    )
    auth = build_auth_response(user)
    response = RedirectResponse(
        url=settings.frontend_url,
        status_code=status.HTTP_302_FOUND,
    )
    response.set_cookie(
        key=settings.access_token_cookie_name,
        value=auth.access_token,
        max_age=settings.access_token_expire_minutes * 60,
        httponly=True,
        secure=settings.cookie_secure,
        samesite="lax",
        path="/",
    )
    response.delete_cookie(
        key=settings.oauth_state_cookie_name,
        path="/",
    )
    return response


@router.get("/me", response_model=AuthUserRead)
async def get_me(current_user: User = Depends(get_current_user)):
    """Return the authenticated user.

    Args:
        current_user: User resolved from the session cookie or Bearer token.

    Returns:
        Public fields for that user.
    """
    return AuthUserRead.model_validate(current_user)



@router.post("/logout", status_code=status.HTTP_204_NO_CONTENT)
async def logout():
    """Clear the session cookie.

    Returns:
        204 with the access-token cookie deleted.
    """
    response = Response(status_code=status.HTTP_204_NO_CONTENT)
    # Cookie deletion must match the attributes used in set_cookie,
    # otherwise browsers keep the httpOnly session cookie.
    response.delete_cookie(
        key=settings.access_token_cookie_name,
        path="/",
        httponly=True,
        secure=settings.cookie_secure,
        samesite="lax",
    )
    return response