# For celery task: sync, create review job, execute review job when github triggers


import logging
import httpx  # pyright: ignore[reportMissingImports]

from sqlalchemy.ext.asyncio import AsyncSession  # pyright: ignore[reportMissingImports]

from app.core.config import get_settings
from app.core.database import AsyncSessionLocal
from app.models.repository import Repository
from app.services.github_pr_files import (
    fetch_github_pull_request_files,
    sync_pull_request_files,
)
from app.services.github_pull_requests import sync_pull_requests
from app.services.github_repositories import list_repo_by_github_repo_id
from app.services.review_jobs import create_review_job
from app.tasks.review_jobs import execute_review_job_task



settings = get_settings()
logger = logging.getLogger(__name__)


async def _sync_and_review_for_repo(
    db: AsyncSession,
    http_client: httpx.AsyncClient,
    repository: Repository,
    github_pr: dict,
) -> None:
    """sync + create_review_job + Celery review task for one local repo"""
    owner = repository.user
    if owner is None or not owner.github_access_token:
        logger.warning(
            "Skip webhook review local_repo_id=%s: owner has no GitHub token",
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

    github_files = await fetch_github_pull_request_files(
        http_client=http_client,
        access_token=owner.github_access_token,
        owner_login=repository.owner_login,
        repo_name=repository.name,
        pull_number=pull_request.number,
    ) 
    await sync_pull_request_files(
        db=db,
        pull_request=pull_request,
        github_files=github_files,
    )

    review_job = await create_review_job(
        db=db,
        pull_request=pull_request,
        provider="openrouter",
        model_name=settings.open_router_default_model,
    )
    execute_review_job_task.delay(review_job.id)
    logger.info(
            "Webhook created review_job_id=%s local_repo_id=%s pr_number=%s files=%s",
            review_job.id,
            repository.id,
            pull_request.number,
            len(github_files),
    )



async def process_github_pull_request_event(payload: dict) -> None:
    """
    run after HTTP webhook has already returned 2xx.
    Maps github repo id -> local owner token, then existing pipeline
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
