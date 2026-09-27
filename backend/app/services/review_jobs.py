import asyncio
import logging
from datetime import datetime, timedelta, timezone

import httpx  # pyright: ignore[reportMissingImports]
from billiard.exceptions import SoftTimeLimitExceeded  # pyright: ignore[reportMissingImports]

from sqlalchemy import delete, select  # pyright: ignore[reportMissingImports]
from sqlalchemy.ext.asyncio import AsyncSession  # pyright: ignore[reportMissingImports]
from sqlalchemy.orm import selectinload  # pyright: ignore[reportMissingImports]

from app.core.config import get_settings
from app.core.database import AsyncSessionLocal
from app.models.pr_file import PRFile
from app.models.pull_request import PullRequest
from app.models.repository import Repository
from app.models.review_job import ReviewJob, ReviewJobStatus
from app.services.diff_chunking import (
    build_file_windows,
    filter_reviewable_files,
    pack_review_windows,
)
from app.services.github_pr_files import fetch_github_file_text
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
    """Return a pull request only when it belongs to the user.

    Args:
        db: Open async session.
        pull_request_id: Local pull request id.
        user_id: Local user id.

    Returns:
        The pull request, or None when it is missing or owned by someone else.
    """
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
    """Load synced files used as review input.

    Args:
        db: Open async session.
        pull_request_id: Local pull request id.

    Returns:
        File rows for that pull request. Ownership is checked by the caller.
    """
    result = await db.execute(
        select(PRFile).where(PRFile.pull_request_id == pull_request_id)
    )
    return list(result.scalars().all())



async def get_review_job_with_findings_for_user(
    db: AsyncSession,
    review_job_id: int,
    user_id: int,
) -> ReviewJob | None:
    """Load one review job and its findings when the user owns it.

    Args:
        db: Open async session.
        review_job_id: Local review job id.
        user_id: Local user id.

    Returns:
        The job with findings loaded, or None when it is missing or owned
        by someone else.
    """
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
    """Fill a missing file path with the pack's only filename.

    Args:
        findings: Findings parsed from one pack.
        fallback_file_path: Path used when a finding has no ``file_path``.

    Returns:
        Copies of the findings, with empty paths replaced.
    """
    return [
        finding if finding.file_path else finding.model_copy(update={"file_path": fallback_file_path}) for finding in findings
    ]



def _dedup_findings(findings: list[ReviewFindingDraft]) -> list[ReviewFindingDraft]:
    """Drop findings that repeat the same path, lines, summary, and suggestion.

    Args:
        findings: Findings collected from every pack.

    Returns:
        The first copy of each distinct finding, in original order.
    """
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
    """Turn an exception into a non-empty message for ``error_message``.

    Args:
        exc: Failure from a model call or the worker wrapper.

    Returns:
        The exception text, or a fallback sentence when that text is empty.
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
    """Call the model for one payload, retrying empty content, 5xx, and 429.

    Args:
        provider: OpenRouter client for this job's model.
        content: User message for this pack.
        request_label: Log label, usually the pack index and filenames.
        attempt_count: Maximum attempts, including the first call.

    Returns:
        The parsed review.

    Raises:
        TimeoutError: The read timed out. Timeouts are not retried.
        SoftTimeLimitExceeded: The Celery soft limit fired. It is re-raised.
        Exception: The last retryable failure, or a non-retryable error.
    """
    last_exc: Exception | None = None

    for attempt in range(1, attempt_count + 1):
        try:
            return await asyncio.wait_for(
                provider.review_content(content),
                timeout=settings.openrouter_read_timeout,
            )
        except SoftTimeLimitExceeded:
            raise
        except (TimeoutError, httpx.TimeoutException):
            raise
        except Exception as exc:
            last_exc = exc
            if attempt >= attempt_count:
                break
            logger.warning(
                "Review attempt %s/%s failed for %s: %s; sleeping 35s",
                attempt,
                attempt_count,
                request_label,
                exc,
            )
            # Two retries wait 70s total, past a 20 RPM 429 window.
            await asyncio.sleep(35)

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
    """Replace all findings stored for one review job.

    Args:
        db: Open async session. This function flushes and does not commit.
        review_job: Job whose previous findings are deleted.
        pr_files: Files used to attach ``pr_file_id`` from ``file_path``.
        findings: Draft findings to store after de-duplication.

    Returns:
        None.
    """
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
    """Insert a pending review job.

    Args:
        db: Open async session. This function commits.
        pull_request: Pull request being reviewed.
        provider: Review provider name, currently ``openrouter``.
        model_name: Model id stored on the job and later read by the worker.

    Returns:
        The committed job. ``total_chunks`` is 0 until execution finishes.
    """
    pr_files = await get_pull_request_files(db, pull_request.id)
    review_job = ReviewJob(
        pull_request_id=pull_request.id,
        status=ReviewJobStatus.pending,
        provider=provider,
        model_name=model_name,
        total_files=len(pr_files),
        total_chunks=0,
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
    """Return the active job for a pull request, or create one.

    Args:
        db: Open async session.
        pull_request: Pull request to lock and check.
        provider: Provider stored on a newly created job.
        model_name: Model stored on a newly created job.

    Returns:
        The job and True when this call created it. False means an existing
        pending or processing job was reused.

    Raises:
        ValueError: The pull request row disappeared before the lock.
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
    """Pack the pull request and write the review result.

    The session is committed before the model calls. Success is written on a
    new session. A failed pack is recorded and the remaining packs continue.

    Args:
        db: Session used to read the job and files, then committed.
        review_job: Pending or processing job to run.
        http_client: Client used for GitHub file text and OpenRouter.

    Returns:
        The job after it is completed or marked failed.

    Raises:
        SoftTimeLimitExceeded: Re-raised so the Celery wrapper can retry once.
        ValueError: The pull request or job row is missing, or every pack failed.
    """
    job_id = review_job.id
    pr_files = await get_pull_request_files(db, review_job.pull_request_id)
    logger.info(
        "Starting execute_review_job review_job_id=%s pull_request_id=%s total_files=%s",
        job_id,
        review_job.pull_request_id,
        len(pr_files),
    )

    pull_request = await db.get(PullRequest, review_job.pull_request_id)
    if pull_request is None:
        raise ValueError(f"Pull request {review_job.pull_request_id} was not found")
    repo_result = await db.execute(
        select(Repository)
        .options(selectinload(Repository.user))
        .where(Repository.id == pull_request.repository_id)
    )
    repository = repo_result.scalar_one()
    access_token = (
        repository.user.github_access_token if repository.user is not None else None
    )
    # copy scalars so HTTP work never touches the ORM session.
    owner_login = repository.owner_login
    repo_name = repository.name
    provider_name = review_job.provider
    model_name = review_job.model_name


    review_job.status = ReviewJobStatus.processing
    await db.commit()
    # After this commit the connection is returned. Do not query `db` until
    # HTTP finishes, or Neon will see an idle-in-transaction again.

    try:
        if provider_name != "openrouter":
            raise ValueError(f"Unsupported provider: {provider_name}")

        provider = OpenRouterReviewProvider(
            http_client=http_client,
            model_name=model_name,
        )

        windows: list[tuple[str, str]] = []
        fetch_notes: list[str] = []
        for pr_file in filter_reviewable_files(pr_files):
            source_text = None
            if pr_file.status != "removed" and access_token:
                try:
                    source_text = await fetch_github_file_text(
                        http_client,
                        access_token,
                        pr_file.contents_url,
                        owner_login=owner_login,
                        repo_name=repo_name,
                        blob_sha=pr_file.sha,
                    )
                except SoftTimeLimitExceeded:
                    raise
                except Exception as exc:
                    fetch_notes.append(
                        f"{pr_file.filename}: failed to fetch source ({exc})"
                    )
            file_windows = build_file_windows(
                filename=pr_file.filename,
                status=pr_file.status,
                patch=pr_file.patch,
                source_text=source_text,
                context_lines=settings.review_context_lines,
                max_chars=settings.review_pack_max_chars,
            )
            windows.extend((pr_file.filename, window) for window in file_windows)

        if not windows:
            raise ValueError("No reviewable patch content found for this pull request.")

        packs = pack_review_windows(
            windows,
            max_chars=settings.review_pack_max_chars,
        )
        logger.info(
            "Review job %s packed %s window(s) into %s request(s)",
            job_id,
            len(windows),
            len(packs),
        )

        summary_sections: list[str] = []
        all_findings: list[ReviewFindingDraft] = []
        pack_notes = list(fetch_notes)

        for pack in packs:
            pack_label = (
                f"pack {pack.pack_index + 1} [" + ", ".join(pack.filenames) + "]"
            )
            try:
                result = await _review_content_with_retries(
                    provider,
                    pack.content,
                    request_label=pack_label,
                    attempt_count=settings.review_retry_attempts,
                )
            except SoftTimeLimitExceeded:
                raise
            except Exception as pack_exc:
                pack_notes.append(
                    f"{pack_label}: {_format_review_job_error(pack_exc)}"
                )
                continue

            summary_sections.append(f"## {pack_label}\n{result.summary}")
            findings = result.findings
            if len(pack.filenames) == 1:
                findings = _apply_file_path_fallback(findings, pack.filenames[0])
            all_findings.extend(findings)

        if not summary_sections:
            raise ValueError("All review packs failed. " + " | ".join(pack_notes))

        async with AsyncSessionLocal() as write_db:
            saved_job = await write_db.get(ReviewJob, job_id)
            if saved_job is None:
                raise ValueError(f"Review job {job_id} was not found")

            saved_job.result_summary = "\n\n".join(summary_sections)
            saved_job.total_chunks = len(packs)
            saved_job.error_message = "\n".join(pack_notes) if pack_notes else None
            logger.info("Review job %s replacing findings for packed path", job_id)
            await replace_review_findings(
                db=write_db,  # CHANGED: was db=
                review_job=saved_job,  # CHANGED: was review_job
                pr_files=pr_files,
                findings=all_findings,
            )
            saved_job.status = ReviewJobStatus.completed
            logger.info("Review job %s committing completed state", job_id)
            await write_db.commit()
            await write_db.refresh(saved_job)
            logger.info("Review job %s completed successfully", job_id)
            return saved_job

    except SoftTimeLimitExceeded:
        raise
    except Exception as exc:
        logger.exception("Review job %s failed during execution", job_id)
        try:
            await db.rollback()
        except Exception:
            logger.exception("Rollback failed for review_job_id=%s", job_id)
        failed_job = await mark_review_job_failed_by_id(
            job_id,
            _format_review_job_error(exc),
        )
        if failed_job is None:
            raise
        return failed_job



async def execute_review_job_by_id(review_job_id: int) -> ReviewJob | None:
    """Open a new session and run one queued review job.

    Args:
        review_job_id: Local review job id from the Celery message.

    Returns:
        The job after execution, the unchanged terminal job when it is already
        completed or failed, or None when the row does not exist.
    """
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
    """List review jobs for one pull request owned by the user.

    Args:
        db: Open async session.
        pull_request_id: Local pull request id.
        user_id: Local user id.

    Returns:
        Jobs with findings loaded, newest first.
    """
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
    """Mark one review job failed on a fresh session.

    Args:
        review_job_id: Local review job id.
        error_message: Text stored on the job. Blank text is replaced.

    Returns:
        The failed job, or None when the row does not exist.
    """
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
    """Mark processing jobs failed when they have not been updated in time.

    Args:
        older_than_seconds: Age threshold. None uses the configured stale
        processing threshold.

    Returns:
        How many jobs were marked failed.
    """
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