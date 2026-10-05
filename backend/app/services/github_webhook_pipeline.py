# For celery task: sync, create review job, execute review job when github triggers


import logging

import httpx  # pyright: ignore[reportMissingImports]
from app.core.config import get_settings
from app.core.database import AsyncSessionLocal
from app.models.repository import Repository
from app.models.review_job import ReviewJobStatus
from app.services.github_pr_files import (
    fetch_github_pull_request_files,
    sync_pull_request_files,
)
from app.services.github_pull_requests import sync_pull_requests
from app.services.github_repositories import list_repo_by_github_repo_id
from app.services.github_tokens import (
    GitHubTokenUnavailable,
    call_with_github_token,
)
from app.services.review_jobs import create_review_job_if_no_active
from app.tasks.review_jobs import execute_review_job_task
from sqlalchemy.ext.asyncio import AsyncSession  # pyright: ignore[reportMissingImports]

settings = get_settings()
logger = logging.getLogger(__name__)


async def _sync_and_review_for_repo(
    db: AsyncSession,
    http_client: httpx.AsyncClient,
    repository: Repository,
    github_pr: dict,
) -> None:
    """Sync one pull request and enqueue review for one local repository.

    Args:
        db: Open async session.
        http_client: HTTP client used for GitHub file and pull-request calls.
        repository: Local repository whose owner token is used.
        github_pr: ``pull_request`` object from the webhook payload.

    Returns:
        None. Logs and returns when the owner has no token or enqueue fails
        after the job is marked failed.
    """
    owner = repository.user
    if owner is None:
        logger.warning(
            "Skip webhook review local_repo_id=%s: owner is missing",
            repository.id,
        )
        return
    
    synced_prs = await sync_pull_requests(
        db=db,
        repository=repository,
        github_pull_requests=[github_pr]
    )
    pull_request = next(
        (item for item in synced_prs if item.number == github_pr.get("number")),
        None,
    )
    if pull_request is None:
        logger.warning(
            "Skip webhook review local_repo_id=%s: PR number=%s was not synced",
            repository.id,
            github_pr.get("number"),
        )
        return

    try:
        github_files = await call_with_github_token(
            owner.id,
            http_client,
            lambda token: fetch_github_pull_request_files(
                http_client=http_client,
                access_token=token,
                owner_login=repository.owner_login,
                repo_name=repository.name,
                pull_number=pull_request.number,
            ),
        )
    except GitHubTokenUnavailable:
        logger.warning(
            "Skip webhook review local_repo_id=%s pr_number=%s: "
            "GitHub authorization must be renewed",
            repository.id,
            pull_request.number,
        )
        return

    await sync_pull_request_files(
        db=db,
        pull_request=pull_request,
        github_files=github_files,
    )

    # check whether have active job before create new job
    review_job, created = await create_review_job_if_no_active(
        db=db,
        pull_request=pull_request,
        provider="openrouter",
        # Webhook stays on the server default. The browser allowlist does not apply here.
        model_name=settings.open_router_default_model,
    )
    if not created:
        logger.info(
            "Skip webhook review local_repo_id=%s pr_number=%s: "
            "active review_job_id=%s status=%s",
            repository.id,
            pull_request.number,
            review_job.id,
            review_job.status.value,
        )
        return

    try:
        execute_review_job_task.delay(review_job.id)
    except Exception as exc:
        review_job.status = ReviewJobStatus.failed
        review_job.error_message = f"Failed to enqueue review job: {exc}"
        await db.commit()
        logger.exception(
            "Failed to enqueue webhook review_job_id=%s",
            review_job.id,
        )
        raise

    logger.info(
        "Webhook created review_job_id=%s local_repo_id=%s pr_number=%s files=%s",
        review_job.id,
        repository.id,
        pull_request.number,
        len(github_files),
    )



async def process_github_pull_request_event(payload: dict) -> None:
    """Run the webhook pipeline after the HTTP handler has already returned.

    Args:
        payload: Verified ``pull_request`` event body.

    Returns:
        None. Skips the event when the repository is not stored locally or
        the payload has no repository id or pull request number.
    """

    repo_payload = payload.get("repository") or {}
    github_pr = payload.get("pull_request") or {}
    github_repo_id = repo_payload.get("id")
    if github_repo_id is None or not github_pr.get("number"):
        logger.warning("Webhook payload missing repository.id or pull_request.number")
        return

    timeout = httpx.Timeout(
        connect=settings.openrouter_connect_timeout,
        read=settings.openrouter_read_timeout,
        write=30.0,
        pool=30.0,
    )

    async with AsyncSessionLocal() as db:
        local_repos = await list_repo_by_github_repo_id(db, int(github_repo_id))
        if not local_repos:
            logger.info(
                "Skip webhook review github_repo_id=%s: not synced in CodeGuard yet",
                github_repo_id,
            )
            return

        async with httpx.AsyncClient(timeout=timeout) as http_client:
            for repo in local_repos:
                await _sync_and_review_for_repo(
                    db=db,
                    http_client=http_client,
                    repository=repo,
                    github_pr=github_pr,
                ) 
