import httpx  # pyright: ignore[reportMissingImports]
from app.api.deps import get_current_user, get_db
from app.api.rate_limit_deps import limit_pull_request_sync
from app.models.user import User
from app.schemas.pull_request import PullRequestRead, PullRequestSyncResponse
from app.services.github_pull_requests import (
    fetch_github_pull_requests,
    get_repo_for_user,
    list_PRs_for_repo,
    sync_pull_requests,
)
from fastapi import (  # pyright: ignore[reportMissingImports]
    APIRouter,
    Depends,
    HTTPException,
    Request,
    status,
)
from sqlalchemy.ext.asyncio import AsyncSession  # pyright: ignore[reportMissingImports]

router = APIRouter(prefix="/repositories", tags=["pull-requests"])


@router.post(
    "/{repository_id}/pr/sync",
    response_model=PullRequestSyncResponse,
    dependencies=[Depends(limit_pull_request_sync)],
)
async def sync_repo_pr(
    repository_id: int,
    request: Request,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Fetch pull requests from GitHub and store them for one repository.

    Args:
        repository_id: Local repository id.
        request: Incoming request; its app state holds the HTTP client.
        current_user: Authenticated owner of the repository.
        db: Request-scoped async session.

    Returns:
        Pull requests still stored for this repository after the sync, including count.

    Raises:
        HTTPException: 400 without a GitHub token, 404 when the repo is not
        owned by the current user.
    """
    if not current_user.github_access_token:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="User has no GitHub access token",
        )

    repository = await get_repo_for_user(
        db=db,
        repository_id=repository_id,
        user_id=current_user.id,
    )

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
        replace_missing=True,
    )

    return PullRequestSyncResponse(
        count=len(pull_requests),
        items=[PullRequestRead.model_validate(item) for item in pull_requests],
    )


@router.get("/{repository_id}/pull-requests", response_model=PullRequestSyncResponse)
async def list_repository_pull_requests(
    repository_id: int,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """List pull requests already stored for one repository.

    Args:
        repository_id: Local repository id.
        current_user: Authenticated user. The repository must belong to them.
        db: Request-scoped async session.

    Returns:
        Stored pull requests and their count. Does not call GitHub.

    Raises:
        HTTPException: 404 when the repository is not owned by the current user.
    """
    repository = await get_repo_for_user(
        db=db,
        repository_id=repository_id,
        user_id=current_user.id,
    )
    if repository is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Repository not found",
        )
    pull_requests = await list_PRs_for_repo(db, repository_id)
    return PullRequestSyncResponse(
        count=len(pull_requests),
        items=[PullRequestRead.model_validate(item) for item in pull_requests],
    )
