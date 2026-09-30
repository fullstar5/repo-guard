import asyncio
from datetime import datetime, timedelta, timezone
from unittest.mock import AsyncMock, MagicMock, patch

import httpx  # pyright: ignore[reportMissingImports]
import pytest  # pyright: ignore[reportMissingImports]
from celery.exceptions import Retry  # pyright: ignore[reportMissingImports]

from app.models.review_job import ReviewJob, ReviewJobStatus
from app.services.review_jobs import mark_abandoned_jobs_as_failed, mark_review_job_failed_by_id
from app.tasks.review_jobs import _retry_countdown, execute_review_job_task
from helpers import async_cm, scalars_result


def _job(status: ReviewJobStatus, updated_at: datetime) -> ReviewJob:
    job = ReviewJob(
        id=1,
        pull_request_id=10,
        status=status,
        provider="openrouter",
        model_name="openrouter/free",
        total_files=1,
        total_chunks=0,
    )
    job.updated_at = updated_at
    return job


def test_reclaim_marks_only_rows_the_query_returns_and_commits():
    now = datetime(2026, 6, 1, tzinfo=timezone.utc)
    stale = _job(
        ReviewJobStatus.processing,
        now - timedelta(hours=5),
    )
    db = AsyncMock()
    db.execute = AsyncMock(return_value=scalars_result([stale]))

    class FrozenDateTime(datetime):
        @classmethod
        def now(cls, tz=None):
            return now

    with (
        patch("app.services.review_jobs.datetime", FrozenDateTime),
        patch(
            "app.services.review_jobs.AsyncSessionLocal",
            return_value=async_cm(db),
        ),
        patch(
            "app.services.review_jobs.settings.review_job_stale_processing_seconds",
            10800,
        ),
    ):
        cleaned = asyncio.run(mark_abandoned_jobs_as_failed())

    assert cleaned == 1
    assert stale.status == ReviewJobStatus.failed
    assert "10800s" in (stale.error_message or "")
    statement = db.execute.await_args.args[0]
    compiled = statement.compile(compile_kwargs={"render_postcompile": True})
    sql = str(compiled).lower()
    assert "updated_at" in sql
    assert ReviewJobStatus.processing in compiled.params.values()
    db.commit.assert_awaited()


def test_reclaim_does_not_commit_when_nothing_is_stale():
    db = AsyncMock()
    db.execute = AsyncMock(return_value=scalars_result([]))

    with patch(
        "app.services.review_jobs.AsyncSessionLocal",
        return_value=async_cm(db),
    ):
        cleaned = asyncio.run(mark_abandoned_jobs_as_failed(older_than_seconds=10))

    assert cleaned == 0
    db.commit.assert_not_awaited()


def test_mark_failed_replaces_blank_message_and_missing_job():
    job = ReviewJob(
        id=5,
        pull_request_id=1,
        status=ReviewJobStatus.processing,
        provider="openrouter",
        model_name="openrouter/free",
    )
    db = AsyncMock()
    db.get = AsyncMock(side_effect=[job, None])

    with patch(
        "app.services.review_jobs.AsyncSessionLocal",
        return_value=async_cm(db),
    ):
        failed = asyncio.run(mark_review_job_failed_by_id(5, "   "))
        missing = asyncio.run(mark_review_job_failed_by_id(6, "gone"))

    assert failed is job
    assert job.status == ReviewJobStatus.failed
    assert job.error_message == "Review job failed with an empty error message."
    assert missing is None


def test_retry_countdown_doubles_and_caps():
    with (
        patch("app.tasks.review_jobs.settings.celery_task_retry_backoff_seconds", 5),
        patch("app.tasks.review_jobs.settings.celery_task_retry_backoff_max", 300),
    ):
        assert _retry_countdown(1) == 5
        assert _retry_countdown(2) == 10
        assert _retry_countdown(3) == 20
        assert _retry_countdown(10) == 300


def test_transient_error_retries_before_attempts_are_exhausted():
    request = execute_review_job_task.request
    previous = request.retries
    request.retries = 0
    try:
        with (
            patch(
                "app.tasks.review_jobs.execute_review_job_by_id",
                new=AsyncMock(side_effect=httpx.ConnectError("reset")),
            ),
            patch(
                "app.tasks.review_jobs.mark_review_job_failed_by_id",
                new=AsyncMock(),
            ) as mark_failed,
            patch.object(execute_review_job_task, "max_retries", 3),
            patch.object(execute_review_job_task, "retry", side_effect=Retry()) as retry,
        ):
            with pytest.raises(Retry):
                execute_review_job_task.run(review_job_id=7)
        mark_failed.assert_not_awaited()
        retry.assert_called_once()
        assert retry.call_args.kwargs["countdown"] == _retry_countdown(1)
    finally:
        request.retries = previous


def test_non_transient_task_error_marks_failed_without_retry():
    with (
        patch(
            "app.tasks.review_jobs.execute_review_job_by_id",
            new=AsyncMock(side_effect=RuntimeError("")),
        ),
        patch(
            "app.tasks.review_jobs.mark_review_job_failed_by_id",
            new=AsyncMock(),
        ) as mark_failed,
    ):
        with pytest.raises(RuntimeError):
            execute_review_job_task.run(review_job_id=8)

    message = mark_failed.await_args.args[1]
    assert "Worker task failed" in message
    assert "RuntimeError" in message
