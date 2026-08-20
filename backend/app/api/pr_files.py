import httpx
from fastapi import APIRouter, Depends, HTTPException, Request, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import get_current_user, get_db
from app.models.user import User
from app.schemas.pr_file import (
    PullRequestFileListItem,
    PullRequestFileListResponse,
    PullRequestFileRead,
    PullRequestFileSyncResponse,
)
from app.services.github_pr_files import (
    fetch_github_pull_request_files,
    get_pull_request_with_repository,
    sync_pull_request_files,
    list_PR_files
)



router = APIRouter(prefix="/pull-requests", tags=["pull-request-files"])


@router.post("/{pull_request_id}/files/sync", response_model=PullRequestFileSyncResponse)
async def sync_pull_request_files_endpoint(
    pull_request_id: int,
    request: Request,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    if not current_user.github_access_token:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="User has no GitHub access token",
        )

    pull_request, repository = await get_pull_request_with_repository(
        db=db,
        pull_request_id=pull_request_id,
        user_id=current_user.id,
    )

    if pull_request is None or repository is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Pull request not found",
        )

    http_client: httpx.AsyncClient = request.app.state.http_client
    github_files = await fetch_github_pull_request_files(
        http_client=http_client,
        access_token=current_user.github_access_token,
        owner_login=repository.owner_login,
        repo_name=repository.name,
        pull_number=pull_request.number,
    )

    pr_files = await sync_pull_request_files(
        db=db,
        pull_request=pull_request,
        github_files=github_files,
    )

    return PullRequestFileSyncResponse(
        count=len(pr_files),
        items=[PullRequestFileRead.model_validate(item) for item in pr_files],
    )



@router.get("/{pull_request_id}/files", response_model=PullRequestFileListResponse)
async def list_PR_files_endpoint(
    pull_request_id: int,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    pull_request, repository = await get_pull_request_with_repository(
        db=db,
        pull_request_id=pull_request_id,
        user_id=current_user.id,
    )

    if pull_request is None or repository is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Pull request not found",
        )
    
    files = await list_PR_files(db, pull_request_id)
    return PullRequestFileListResponse(
        count=len(files),
        items=[PullRequestFileListItem.model_validate(item) for item in files],
    )