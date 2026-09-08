import asyncio
from unittest.mock import AsyncMock, MagicMock, patch

from sqlalchemy.ext.asyncio import AsyncSession

from app.models.pull_request import PullRequest
from app.models.review_job import ReviewJob, ReviewJobStatus
from app.services.review_jobs import create_review_job_if_no_active


def _result(value):
    result = MagicMock()
    result.scalar_one_or_none.return_value = value
    return result


def test_existing_active_job_is_reused_without_creating_another():
    pull_request = PullRequest(id=10)
    active_job = ReviewJob(
        id=20,
        pull_request_id=10,
        status=ReviewJobStatus.processing,
        provider="openrouter",
        model_name="openrouter/free",
    )
    db = AsyncMock(spec=AsyncSession)
    db.execute.side_effect = [
        _result(pull_request),
        _result(active_job),
    ]

    with patch(
        "app.services.review_jobs.create_review_job",
        new=AsyncMock(),
    ) as create_job:
        review_job, created = asyncio.run(
            create_review_job_if_no_active(
                db=db,
                pull_request=pull_request,
                provider="openrouter",
                model_name="openrouter/free",
            )
        )

    assert review_job is active_job
    assert created is False
    create_job.assert_not_awaited()
    assert "FOR UPDATE" in str(db.execute.await_args_list[0].args[0])


def test_missing_active_job_uses_existing_create_function():
    pull_request = PullRequest(id=10)
    created_job = ReviewJob(
        id=21,
        pull_request_id=10,
        status=ReviewJobStatus.pending,
        provider="openrouter",
        model_name="openrouter/free",
    )
    db = AsyncMock(spec=AsyncSession)
    db.execute.side_effect = [
        _result(pull_request),
        _result(None),
    ]

    with patch(
        "app.services.review_jobs.create_review_job",
        new=AsyncMock(return_value=created_job),
    ) as create_job:
        review_job, created = asyncio.run(
            create_review_job_if_no_active(
                db=db,
                pull_request=pull_request,
                provider="openrouter",
                model_name="openrouter/free",
            )
        )

    assert review_job is created_job
    assert created is True
    create_job.assert_awaited_once_with(
        db=db,
        pull_request=pull_request,
        provider="openrouter",
        model_name="openrouter/free",
    )
