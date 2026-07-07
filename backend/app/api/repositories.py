import httpx
from fastapi import APIRouter, Depends, HTTPException, Request, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import get_current_user, get_db
from app.models.user import User
from app.schemas.repository import RepositoryRead, RepositorySyncResponse
from app.services.github_repositories import fetch_github_repositories, sync_repositories


router = APIRouter(prefix="/repositories", tags=["repositories"])



@router.post("/sync", response_model=RepositorySyncResponse)
async def sync_user_repositories(
    request: Request,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
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