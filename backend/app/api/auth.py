from secrets import token_urlsafe

import httpx

from fastapi import APIRouter, Depends, HTTPException, Request, status
from fastapi.responses import RedirectResponse
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import get_current_user, get_db
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

@router.get("/github/login")
async def github_login() -> RedirectResponse:
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


@router.get("/github/callback", response_model=GitHubOAuthCallbackResponse)
async def github_callback(
    code: str,
    state: str,
    request: Request,
    db: AsyncSession = Depends(get_db),
):
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

    return build_auth_response(user)


@router.get("/me", response_model=AuthUserRead)
async def get_me(current_user: User = Depends(get_current_user)):
    return AuthUserRead.model_validate(current_user)