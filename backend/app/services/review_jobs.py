import httpx

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import get_settings
from app.models.pr_file import PRFile
from app.models.pull_request import PullRequest
from app.models.repository import Repository
from app.models.review_job import ReviewJob, ReviewJobStatus
from app.services.diff_chunking import build_review_chunks, build_combined_review_input
from app.services.openrouter_provider import OpenRouterReviewProvider

# Pull synced PR data from the database, then create and execute review jobs.
settings = get_settings()

async def get_pull_request_for_user(
    db: AsyncSession,
    pull_request_id: int,
    user_id: int,
) -> PullRequest | None:
    """Return a pull request only when it belongs to the current user scope."""
    result = await db.execute(
        select(PullRequest)
        .join(Repository, PullRequest.repository_id == Repository.id)
        .where(
            PullRequest.id == pull_request_id,
            Repository.user_id == user_id,
        )
    )
    return result.scalar_one_or_none()


async def get_pull_request_files(
    db: AsyncSession,
    pull_request_id: int,
) -> list[PRFile]:
    """Load synced PR files used as review input."""
    result = await db.execute(
        select(PRFile).where(PRFile.pull_request_id == pull_request_id)
    )
    return list(result.scalars().all())


async def create_review_job(
    db: AsyncSession,
    pull_request: PullRequest,
    provider: str,
    model_name: str,
) -> ReviewJob:
    """Create a review job after counting files and chunks."""
    pr_files = await get_pull_request_files(db, pull_request.id)

    combined_input = build_combined_review_input(
        pr_files,
        max_combined_chars=settings.review_max_combined_chars,
        max_combined_files=settings.review_max_combined_files,
    )

    if combined_input is not None:
        total_chunks = 1
    else:
        total_chunks = len(
            build_review_chunks(pr_files, max_patch_chars=settings.review_max_patch_chars)
        )

    review_job = ReviewJob(
        pull_request_id=pull_request.id,
        status=ReviewJobStatus.pending,
        provider=provider,
        model_name=model_name,
        total_files=len(pr_files),
        total_chunks=total_chunks,
    )
    db.add(review_job)

    await db.commit()
    await db.refresh(review_job)

    return review_job


async def execute_review_job(
    db: AsyncSession,
    review_job: ReviewJob,
    http_client: httpx.AsyncClient,
) -> ReviewJob:
    """Run a review job synchronously using the configured online provider."""
    pr_files = await get_pull_request_files(db, review_job.pull_request_id)
    chunks = build_review_chunks(pr_files)

    review_job.status = ReviewJobStatus.processing
    await db.commit()

    try:
        if review_job.provider != "openrouter":
            raise ValueError(f"Unsupported provider: {review_job.provider}")

        provider = OpenRouterReviewProvider(
            http_client=http_client,
            model_name=review_job.model_name,
        )

        combined_input = build_combined_review_input(
            pr_files,
            max_combined_chars=settings.review_max_combined_chars,
            max_combined_files=settings.review_max_combined_files,
        )

        if combined_input is not None:
            # Fast path: review the whole PR in one request.
            review_output = await provider.review_content(combined_input)
            review_job.result_summary = review_output
            review_job.total_chunks = 1
        else:
            # Fallback path: split oversized PRs into smaller reviewable units.
            chunks = build_review_chunks(
                pr_files,
                max_patch_chars=settings.review_max_patch_chars,
            )
            outputs: list[str] = []

            for chunk in chunks:
                result = await provider.review_content(chunk.content)
                outputs.append(
                    f"## {chunk.filename} [chunk {chunk.chunk_index}]\n{result}"
                )

            review_job.result_summary = "\n\n".join(outputs)
            review_job.total_chunks = len(chunks)
        
        review_job.status = ReviewJobStatus.completed
        review_job.error_message = None


    except Exception as exc:
        review_job.status = ReviewJobStatus.failed
        review_job.error_message = str(exc)

    await db.commit()
    await db.refresh(review_job)

    return review_job
