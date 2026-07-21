import httpx

from sqlalchemy import select, delete
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.core.config import get_settings
from app.models.pr_file import PRFile
from app.models.pull_request import PullRequest
from app.models.repository import Repository
from app.models.review_job import ReviewJob, ReviewJobStatus
from app.services.diff_chunking import build_review_chunks, build_combined_review_input
from app.services.openrouter_provider import OpenRouterReviewProvider
from app.models.review_finding import ReviewFinding, ReviewFindingSeverity
from app.services.review_provider import ReviewFindingDraft




# pull PR and PR files from database and create/execute review jobs, and store jobs and results in database 
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
            review_result = await provider.review_content(combined_input)
            review_job.result_summary = review_result.summary
            review_job.total_chunks = 1

            await replace_review_findings(
                db=db,
                review_job=review_job,
                pr_files=pr_files,
                findings=review_result.findings,
            )
        else:
            # Fallback path: split oversized PRs into smaller reviewable units.
            chunks = build_review_chunks(
                pr_files,
                max_patch_chars=settings.review_max_patch_chars,
            )
            summary_sections: list[str] = []
            all_findings: list[ReviewFindingDraft] = []

            for chunk in chunks:
                result = await provider.review_content(chunk.content)
                summary_sections.append(
                    f"## {chunk.filename} [chunk {chunk.chunk_index + 1}]\n{result.summary}"
                )
                all_findings.extend(
                    _apply_file_path_fallback(result.findings, chunk.filename)
                )

            review_job.result_summary = "\n\n".join(summary_sections)
            review_job.total_chunks = len(chunks)

            await replace_review_findings(
                db=db,
                review_job=review_job,
                pr_files=pr_files,
                findings=all_findings,
            )
        
        review_job.status = ReviewJobStatus.completed
        review_job.error_message = None

        await db.commit()
        await db.refresh(review_job)
        return review_job

    except Exception as exc:
        await db.rollback()


        failed_job = await db.get(ReviewJob, review_job.id)
        if failed_job is None:
            raise
        failed_job.status = ReviewJobStatus.failed
        failed_job.error_message = str(exc)

        await db.commit()
        await db.refresh(failed_job)
        return failed_job
