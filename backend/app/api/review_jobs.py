from fastapi import APIRouter, Depends, HTTPException, status  # pyright: ignore[reportMissingImports]
from sqlalchemy.ext.asyncio import AsyncSession  # pyright: ignore[reportMissingImports]

from app.api.deps import get_current_user, get_db
from app.api.rate_limit_deps import limit_review_creation
from app.core.config import REVIEW_MODEL_ALLOWLIST, get_settings
from app.models.review_job import ReviewJobStatus
from app.models.user import User
from app.schemas.review_job import (
    CreateReviewJobRequest,
    ReviewJobListResponse,
    ReviewJobRead,
    ReviewModelListResponse,
)
from app.services.review_jobs import (
    create_review_job_if_no_active,
    get_pull_request_for_user,
    get_review_job_with_findings_for_user,
    list_review_jobs_for_pull_request_for_user,
)
from app.tasks.review_jobs import execute_review_job_task

router = APIRouter(tags=["review-jobs"])
settings = get_settings()


@router.get("/review-models", response_model=ReviewModelListResponse)
async def list_review_models(
    current_user: User = Depends(get_current_user),
):
    """Return the models a user may pick for a manual review."""
    default_model = settings.open_router_default_model
    if default_model not in REVIEW_MODEL_ALLOWLIST:
        default_model = REVIEW_MODEL_ALLOWLIST[0]
    return ReviewModelListResponse(
        models=list(REVIEW_MODEL_ALLOWLIST),
        default_model=default_model,
    )


@router.post(
    "/pull-requests/{pull_request_id}/review-jobs",
    response_model=ReviewJobRead,
    status_code=status.HTTP_202_ACCEPTED,
    dependencies=[Depends(limit_review_creation)],
)
async def create_pull_request_review_job(
    pull_request_id: int,
    payload: CreateReviewJobRequest,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Create one review job and enqueue it for background execution."""
    pull_request = await get_pull_request_for_user(
        db=db,
        pull_request_id=pull_request_id,
        user_id=current_user.id,
    )

    if pull_request is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Pull request not found",
        )

    review_job, created = await create_review_job_if_no_active(
        db=db,
        pull_request=pull_request,
        provider=payload.provider,
        model_name=payload.model_name,
    )

    if created:
        try:
            execute_review_job_task.delay(review_job.id)
        except Exception as exc:
            review_job.status = ReviewJobStatus.failed
            review_job.error_message = f"Failed to enqueue review job: {exc}"
            await db.commit()
            await db.refresh(review_job)

            raise HTTPException(
                status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
                detail="Failed to enqueue review job",
            ) from exc

    review_job_with_findings = await get_review_job_with_findings_for_user(
        db=db,
        review_job_id=review_job.id,
        user_id=current_user.id,
    )
    if review_job_with_findings is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Review job not found",
        )

    return ReviewJobRead.model_validate(review_job_with_findings)




@router.get("/review-jobs/{review_job_id}", response_model=ReviewJobRead)
async def get_review_job_by_id_and_user(
    review_job_id: int,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Fetch one review job with nested findings for the current user."""
    review_job = await get_review_job_with_findings_for_user(
        db=db,
        review_job_id=review_job_id,
        user_id=current_user.id,
    )

    if review_job is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Review job not found",
        )

    return ReviewJobRead.model_validate(review_job)



@router.get("/pull-requests/{pull_request_id}/review-jobs", response_model=ReviewJobListResponse)
async def list_pull_request_review_jobs(
    pull_request_id: int,
    current_user: User=Depends(get_current_user),
    db: AsyncSession=Depends(get_db),
): 
    """list all review jobs for one pull request for current user"""


    # verify if pr is exist
    pull_request = await get_pull_request_for_user(
        db=db,
        pull_request_id=pull_request_id,
        user_id=current_user.id,
    )
    if pull_request is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Pull request not found",
        )

    review_jobs = await list_review_jobs_for_pull_request_for_user(
        db=db,
        pull_request_id=pull_request_id,
        user_id=current_user.id,
    )

    return ReviewJobListResponse(
        count=len(review_jobs),
        items=[ReviewJobRead.model_validate(item) for item in review_jobs],
    )
