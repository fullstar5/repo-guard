import asyncio
import logging
from datetime import datetime, timedelta, timezone

import httpx  # pyright: ignore[reportMissingImports]

from sqlalchemy import delete, select  # pyright: ignore[reportMissingImports]
from sqlalchemy.ext.asyncio import AsyncSession  # pyright: ignore[reportMissingImports]
from sqlalchemy.orm import selectinload  # pyright: ignore[reportMissingImports]

from app.core.config import get_settings
from app.core.database import AsyncSessionLocal
from app.models.pr_file import PRFile
from app.models.pull_request import PullRequest
from app.models.repository import Repository
from app.models.review_job import ReviewJob, ReviewJobStatus
from app.services.diff_chunking import build_review_chunks, build_combined_review_input
from app.services.openrouter_provider import OpenRouterReviewProvider
from app.models.review_finding import ReviewFinding, ReviewFindingSeverity
from app.services.review_provider import ReviewFindingDraft, ReviewResult




# pull PR and PR files from database and create/execute review jobs, and store jobs and results in database 
settings = get_settings()
logger = logging.getLogger(__name__)

ACTIVE_REVIEW_JOB_STATUSES = (
    ReviewJobStatus.pending,
    ReviewJobStatus.processing,
)



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



async def get_review_job_with_findings_for_user(
    db: AsyncSession,
    review_job_id: int,
    user_id: int,
) -> ReviewJob | None:
    """Load one review job with nested findings, scoped to the current user."""
    result = await db.execute(
        select(ReviewJob)
        .join(PullRequest, ReviewJob.pull_request_id == PullRequest.id)
        .join(Repository, PullRequest.repository_id == Repository.id)
        .options(selectinload(ReviewJob.findings))
        .where(
            ReviewJob.id == review_job_id,
            Repository.user_id == user_id,
        )
    )
    return result.scalar_one_or_none()



def _apply_file_path_fallback(
    findings: list[ReviewFindingDraft],
    fallback_file_path: str,
) -> list[ReviewFindingDraft]:
    """only use in chunk mode, fill the file path for any empty file path in AI response"""
    return [
        finding if finding.file_path else finding.model_copy(update={"file_path": fallback_file_path}) for finding in findings
    ]



def _dedup_findings(findings: list[ReviewFindingDraft]) -> list[ReviewFindingDraft]:
    """remove duplicate findings"""
    dedup: list[ReviewFindingDraft] = []
    seen: set[tuple[str, int | None, int | None, str, str]] = set()

    for finding in findings:
        key = (
            finding.file_path or "",
            finding.start_line,
            finding.end_line,
            " ".join(finding.summary.lower().split()),
            " ".join((finding.suggestion or "").lower().split()),
        )

        if key in seen:
            continue
        seen.add(key)
        dedup.append(finding)
    
    return dedup




def _format_review_job_error(exc: BaseException) -> str:
    """
    Never return empty string error to database,
    """
    if isinstance(exc, TimeoutError):
        message = str(exc).strip()
        if message:
            return message
        return (
            "Review attempt timed out after "
            f"{settings.openrouter_read_timeout:.0f}s waiting for the model."
        )
    message = str(exc).strip()
    if message:
        return message
    return f"{type(exc).__name__}: review job failed with an empty exception message."




async def _review_content_with_retries(
    provider: OpenRouterReviewProvider,
    content: str,
    *,
    request_label: str,
    attempt_count: int = 3,
) -> ReviewResult:
    """Review content with 3 retries"""
    last_exc: Exception | None = None

    for attempt in range(1, attempt_count + 1):
        try:
            # httpx read timeout only applies per socket read. A slow model can
            # keep the connection alive for many minutes. Cap each attempt.
            return await asyncio.wait_for(
                provider.review_content(content),
                timeout=settings.openrouter_read_timeout,
            )
        except Exception as exc:
            if isinstance(exc, TimeoutError) and not str(exc).strip():
                exc = TimeoutError(
                    "Review attempt timed out after "
                    f"{settings.openrouter_read_timeout:.0f}s waiting for the model."
                )
            last_exc = exc
            logger.warning(
                "Review attempt %s/%s failed for %s: %s",
                attempt,
                attempt_count,
                request_label,
                exc,
            )

    assert last_exc is not None
    logger.error(
        "Review failed after %s attempts for %s: %s",
        attempt_count,
        request_label,
        last_exc,
    )
    raise last_exc



async def replace_review_findings(
    db: AsyncSession,
    review_job: ReviewJob,
    pr_files: list[PRFile],
    findings: list[ReviewFindingDraft],
) -> None:
    """Replace all findings for one review job."""
    await db.execute(
        delete(ReviewFinding).where(ReviewFinding.review_job_id == review_job.id)
    )
    file_id_by_path = {pr_file.filename: pr_file.id for pr_file in pr_files}
    for finding in _dedup_findings(findings):
        db.add(
            ReviewFinding(
                review_job_id=review_job.id,
                pr_file_id=file_id_by_path.get(finding.file_path or ""),
                severity=ReviewFindingSeverity(finding.severity),
                summary=finding.summary,
                file_path=finding.file_path,
                start_line=finding.start_line,
                end_line=finding.end_line,
                suggestion=finding.suggestion,
            )
        )
    await db.flush()



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
        max_combined_changes=settings.review_max_combined_changes,
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



async def create_review_job_if_no_active(
    db: AsyncSession,
    pull_request: PullRequest,
    provider: str,
    model_name: str,
) -> tuple[ReviewJob, bool]:
    """
    return existing active job or create new one
    """

    locked_pull_request_result = await db.execute(
        select(PullRequest).where(PullRequest.id == pull_request.id).with_for_update()
    )
    locked_pull_request = locked_pull_request_result.scalar_one_or_none()

    if locked_pull_request is None:
        raise ValueError(
            f"Pull request {pull_request.id} no longer exists"
        )

    active_job_result = await db.execute(
        select(ReviewJob)
        .where(
            ReviewJob.pull_request_id == locked_pull_request.id,
            ReviewJob.status.in_(ACTIVE_REVIEW_JOB_STATUSES),
        )
        .order_by(ReviewJob.created_at.desc())
        .limit(1)
    )
    active_job = active_job_result.scalar_one_or_none()

    # if one active job already exist
    if active_job is not None:
        logger.info(
            "Reuse active review_job_id=%s pull_request_id=%s status=%s",
            active_job.id,
            locked_pull_request.id,
            active_job.status.value,
        )
        return active_job, False

    review_job = await create_review_job(
        db=db,
        pull_request=locked_pull_request,
        provider=provider,
        model_name=model_name,
    )
    return review_job, True




async def execute_review_job(
    db: AsyncSession,
    review_job: ReviewJob,
    http_client: httpx.AsyncClient,
) -> ReviewJob:
    """Run a review job synchronously using the configured online provider."""
    pr_files = await get_pull_request_files(db, review_job.pull_request_id)
    logger.info(
        "Starting execute_review_job review_job_id=%s pull_request_id=%s total_files=%s",
        review_job.id,
        review_job.pull_request_id,
        len(pr_files),
    )

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
            max_combined_changes=settings.review_max_combined_changes,
        )

        if combined_input is not None:
            logger.info("Review job %s using combined-input path", review_job.id)
            # Fast path: review the whole PR in one request.
            review_result = await _review_content_with_retries(
                provider,
                combined_input,
                request_label="combined review",
                attempt_count=settings.review_retry_attempts,
            )
            logger.info("Review job %s finished provider call for combined path", review_job.id)
            review_job.result_summary = review_result.summary
            review_job.total_chunks = 1
            review_job.error_message = None

            logger.info("Review job %s replacing findings for combined path", review_job.id)
            await replace_review_findings(
                db=db,
                review_job=review_job,
                pr_files=pr_files,
                findings=review_result.findings,
            )
        else:
            logger.info("Review job %s using chunked path", review_job.id)
            # Fallback path: split oversized PRs into smaller reviewable units.
            chunks = build_review_chunks(
                pr_files,
                max_patch_chars=settings.review_max_patch_chars,
            )
            if not chunks:
                raise ValueError("No reviewable patch content found for this pull request.")
            summary_sections: list[str] = []
            all_findings: list[ReviewFindingDraft] = []
            chunk_errors: list[str] = []

            for chunk in chunks:
                chunk_label = f"{chunk.filename} [chunk {chunk.chunk_index + 1}]"

                try:
                    result = await _review_content_with_retries(
                        provider,
                        chunk.content,
                        request_label=chunk_label,
                        attempt_count=settings.review_retry_attempts,
                    )
                except Exception as exc:
                    chunk_errors.append(
                        f"{chunk_label}: failed after {settings.review_retry_attempts} attempts: {exc}"
                    )
                    continue

                summary_sections.append(f"## {chunk_label}\n{result.summary}")
                all_findings.extend(
                    _apply_file_path_fallback(result.findings, chunk.filename)
                )
            
            if not summary_sections:
                raise ValueError("All review chunks failed. " + " | ".join(chunk_errors))

            review_job.result_summary = "\n\n".join(summary_sections)
            review_job.total_chunks = len(chunks)
            review_job.error_message = "\n".join(chunk_errors) if chunk_errors else None

            logger.info("Review job %s replacing findings for chunked path", review_job.id)
            await replace_review_findings(
                db=db,
                review_job=review_job,
                pr_files=pr_files,
                findings=all_findings,
            )
        
        review_job.status = ReviewJobStatus.completed
        logger.info("Review job %s committing completed state", review_job.id)

        await db.commit()
        await db.refresh(review_job)
        logger.info("Review job %s completed successfully", review_job.id)
        return review_job

    except Exception as exc:
        await db.rollback()


        failed_job = await db.get(ReviewJob, review_job.id)
        if failed_job is None:
            raise
        failed_job.status = ReviewJobStatus.failed
        failed_job.error_message = _format_review_job_error(exc)

        await db.commit()
        await db.refresh(failed_job)
        return failed_job



async def execute_review_job_by_id(review_job_id: int) -> ReviewJob | None:
    """Load one review job in a fresh async session (rabbitMQ and celery) and execute it."""
    async with AsyncSessionLocal() as db:
        review_job = await db.get(ReviewJob, review_job_id)
        if review_job is None:
            logger.warning("Review job %s was not found", review_job_id)
            return None
        
        # if the job has failed or completed, skip
        TERMINAL = {ReviewJobStatus.completed, ReviewJobStatus.failed}
        if review_job.status in TERMINAL:
            logger.info(
                "Skip review_job=%s because status=%s ",
                review_job.id,
                review_job.status.value,
            )
            return review_job

        timeout = httpx.Timeout(
            connect=settings.openrouter_connect_timeout,
            read=settings.openrouter_read_timeout,
            write=30.0,
            pool=30.0,
        )

        async with httpx.AsyncClient(timeout=timeout) as http_client:
            return await execute_review_job(
                db=db,
                review_job=review_job,
                http_client=http_client,
            )


async def list_review_jobs_for_pull_request_for_user(
    db: AsyncSession,
    pull_request_id: int,
    user_id: int,
) -> list[ReviewJob]:
    """list review jobs for one pull request, scoped to the current user"""
    res = await db.execute(
        select(ReviewJob).join(PullRequest, ReviewJob.pull_request_id == PullRequest.id)
        .join(Repository, PullRequest.repository_id == Repository.id)
        .options(selectinload(ReviewJob.findings))
        .where(
            ReviewJob.pull_request_id == pull_request_id,
            Repository.user_id == user_id,
        ).order_by(ReviewJob.created_at.desc())
    )

    return list(res.scalars().all())



async def mark_review_job_failed_by_id(
    review_job_id: int,
    error_message: str,
) -> ReviewJob | None:
    """Mark review job as failed (exceed time limit, out of retriesetc)"""
    async with AsyncSessionLocal() as db:
        review_job = await db.get(ReviewJob, review_job_id)
        if review_job is None:
            logger.warning("Review job %s was not found while marking failed.", review_job_id)
            return None

        review_job.status = ReviewJobStatus.failed
        review_job.error_message = (
            error_message.strip()
            or "Review job failed with an empty error message."
        )

        await db.commit()
        await db.refresh(review_job)
        return review_job



async def mark_abandoned_jobs_as_failed(
    older_than_seconds: int | None = None,
) -> int:
    """Mark abandoned job as failed. Call by celery"""
    threshold = older_than_seconds or settings.review_job_stale_processing_seconds
    cutoff = datetime.now(timezone.utc) - timedelta(seconds=threshold)

    async with AsyncSessionLocal() as db:
        result = await db.execute(
            select(ReviewJob).where(
                ReviewJob.status == ReviewJobStatus.processing,
                ReviewJob.updated_at < cutoff,
            )
        )

        jobs = list(result.scalars().all())
        for job in jobs:
            job.status = ReviewJobStatus.failed
            job.error_message = (
                "Mark stale process job as failed"
                f"(no update for {threshold}s)."
            )
            logger.warning(
                "Mark stale review_job_id=%s updated_at=%s",
                job.id,
                job.updated_at,
            )

        if jobs:
            await db.commit()
        return len(jobs)