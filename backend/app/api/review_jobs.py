import httpx

from fastapi import APIRouter, Depends, HTTPException, Request, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import get_current_user, get_db
from app.models.user import User
from app.schemas.review_job import CreateReviewJobRequest, ReviewJobRead
from app.services.review_jobs import (
    create_review_job,
    execute_review_job,
    get_pull_request_for_user,
    get_review_job_with_findings_for_user,
)

router = APIRouter(tags=["review-jobs"])


@router.post("/pull-requests/{pull_request_id}/review-jobs", response_model=ReviewJobRead)
async def create_pull_request_review_job(
    pull_request_id: int,
    payload: CreateReviewJobRequest,
    request: Request,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Create and execute a review job for one pull request."""
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

    review_job = await create_review_job(
        db=db,
        pull_request=pull_request,
        provider=payload.provider,
        model_name=payload.model_name,
    )

    http_client: httpx.AsyncClient = request.app.state.http_client
    review_job = await execute_review_job(
        db=db,
        review_job=review_job,
        http_client=http_client,
    )

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
    """Fetch one review job with nested findings for the current user"""
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