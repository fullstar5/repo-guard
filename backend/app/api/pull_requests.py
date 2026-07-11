import httpx
from fastapi import APIRouter, Depends, HTTPException, Request, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import get_current_user, get_db
from app.models.repository import Repository
from app.models.user import User
from app.schemas.pull_request import PullRequestRead, PullRequestSyncResponse
from app.services.github_pull_requests import fetch_github_pull_requests, sync_pull_requests


router = APIRouter(prefix="/repositories", tags=["pull-requests"])


@router.post("/{repository_id}/pr/sync", response_model=PullRequestSyncResponse)
async def sync_repo_pr(
    repository_id: int,
    request: Request,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    if not current_user.github_access_token:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="User has no GitHub access token",
        )
    
    result = await db.execute(
        select(Repository).where(
            Repository.id == repository_id,
            Repository.user_id == current_user.id,
        )
    )
    repository = result.scalar_one_or_none()

    if repository is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Repository not found",
        )

    http_client: httpx.AsyncClient = request.app.state.http_client
    github_pull_requests = await fetch_github_pull_requests(
        http_client=http_client,
        access_token=current_user.github_access_token,
        owner_login=repository.owner_login,
        repo_name=repository.name,
    )

    pull_requests = await sync_pull_requests(
        db=db,
        repository=repository,
        github_pull_requests=github_pull_requests,
    )

    return PullRequestSyncResponse(
        count=len(pull_requests),
        items=[PullRequestRead.model_validate(item) for item in pull_requests],
    )