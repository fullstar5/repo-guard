import httpx  # pyright: ignore[reportMissingImports]
from fastapi import APIRouter, Depends, HTTPException, Request, status  # pyright: ignore[reportMissingImports]
from sqlalchemy.ext.asyncio import AsyncSession  # pyright: ignore[reportMissingImports]

from app.api.deps import get_current_user, get_db
from app.api.rate_limit_deps import limit_repository_sync
from app.models.user import User
from app.schemas.repository import RepositoryRead, RepositorySyncResponse
from app.services.github_repositories import (
    fetch_github_repositories,
    list_repos_for_user,
    sync_repositories,
)


router = APIRouter(prefix="/repositories", tags=["repositories"])



@router.post(
    "/sync",
    response_model=RepositorySyncResponse,
    dependencies=[Depends(limit_repository_sync)],
)
async def sync_user_repositories(
    request: Request,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Replace the user's stored repositories with the current GitHub list.

    Args:
        request: Incoming request; its app state holds the HTTP client.
        current_user: Authenticated user whose GitHub token is used.
        db: Request-scoped async session.

    Returns:
        Repositories remaining after sync, including count.

    Raises:
        HTTPException: 400 when the user has no GitHub token.
    """
    if not current_user.github_access_token:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="User has no Github access token",
        )

    http_client: httpx.AsyncClient = request.app.state.http_client
    github_repositories = await fetch_github_repositories(
        http_client,
        current_user.github_access_token,
    )
    repositories = await sync_repositories(db, current_user, github_repositories)

    return RepositorySyncResponse(
        count=len(repositories),
        items=[RepositoryRead.model_validate(item) for item in repositories]
    )



@router.get("", response_model=RepositorySyncResponse)
async def list_user_repos(
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """List repositories stored for the current user.

    Args:
        current_user: Authenticated user.
        db: Request-scoped async session.

    Returns:
        Stored repositories and their count. Does not call GitHub.
    """
    repos = await list_repos_for_user(db, current_user.id)
    return RepositorySyncResponse(
        count=len(repos),
        items=[RepositoryRead.model_validate(item) for item in repos],
    )