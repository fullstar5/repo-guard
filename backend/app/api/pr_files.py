import httpx  # pyright: ignore[reportMissingImports]
from fastapi import APIRouter, Depends, HTTPException, Request, status  # pyright: ignore[reportMissingImports]
from sqlalchemy.ext.asyncio import AsyncSession  # pyright: ignore[reportMissingImports]

from app.api.deps import get_current_user, get_db
from app.api.rate_limit_deps import limit_file_sync
from app.schemas.pull_request import PullRequestRead
from app.models.user import User
from app.schemas.pr_file import (
    PullRequestFileListItem,
    PullRequestFileListResponse,
    PullRequestFileRead,
    PullRequestFileSyncResponse,
)
from app.services.github_pr_files import (
    fetch_github_pull_request_files,
    get_PR_file_for_user,
    get_pull_request_with_repository,
    list_PR_files,
    sync_pull_request_files,
)



router = APIRouter(prefix="/pull-requests", tags=["pull-request-files"])


@router.post(
    "/{pull_request_id}/files/sync",
    response_model=PullRequestFileSyncResponse,
    dependencies=[Depends(limit_file_sync)],
)
async def sync_pull_request_files_endpoint(
    pull_request_id: int,
    request: Request,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Fetch changed files from GitHub and store them for one pull request.

    Args:
        pull_request_id: Local pull request id.
        request: Incoming request; its app state holds the HTTP client.
        current_user: Authenticated owner of the repository.
        db: Request-scoped async session.

    Returns:
        The file rows written by this sync, including patches and count.

    Raises:
        HTTPException: 400 without a GitHub token, 404 when the pull request
        is not owned by the current user.
    """
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
    """List changed files stored for one pull request.

    Args:
        pull_request_id: Local pull request id.
        current_user: Authenticated user. The pull request must belong to them.
        db: Request-scoped async session.

    Returns:
        File list items without requiring a new GitHub call.

    Raises:
        HTTPException: 404 when the pull request is not owned by the current user.
    """
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


@router.get(
    "/{pull_request_id}/files/{file_id}",
    response_model=PullRequestFileRead,
)
async def get_PR_file(
    pull_request_id: int,
    file_id: int,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Return one synced file, including its patch.

    Args:
        pull_request_id: Local pull request id.
        file_id: Local pull-request file id.
        current_user: Authenticated user. The file must belong to them.
        db: Request-scoped async session.

    Returns:
        The file row, including patch text.

    Raises:
        HTTPException: 404 when the file is missing or belongs to another user.
    """
    pr_file = await get_PR_file_for_user(
        db=db,
        pull_request_id=pull_request_id,
        file_id=file_id,
        user_id=current_user.id,
    )
    if pr_file is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Pull request file not found",
        )
    return PullRequestFileRead.model_validate(pr_file)



@router.get("/{pull_request_id}", response_model=PullRequestRead)
async def get_pull_request(
    pull_request_id: int,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Return one stored pull request.

    Args:
        pull_request_id: Local pull request id.
        current_user: Authenticated user. The pull request must belong to them.
        db: Request-scoped async session.

    Returns:
        The pull request row.

    Raises:
        HTTPException: 404 when it is missing or belongs to another user.
    """
    pull_request, repository = await get_pull_request_with_repository(
        db=db,
        pull_request_id=pull_request_id,
        user_id=current_user.id,
    )
    if pull_request is None or repository is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Pull Reqeust not found",
        )
    return PullRequestRead.model_validate(pull_request)