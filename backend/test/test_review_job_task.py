from unittest.mock import AsyncMock, patch

import httpx
import pytest
from billiard.exceptions import SoftTimeLimitExceeded

from app.tasks.review_jobs import execute_review_job_task, mark_abandoned_jobs


def test_soft_timeout_persists_failed_status():
    with (
        patch(
            "app.tasks.review_jobs.execute_review_job_by_id",
            new=AsyncMock(side_effect=SoftTimeLimitExceeded()),
        ),
        patch(
            "app.tasks.review_jobs.mark_review_job_failed_by_id",
            new=AsyncMock(return_value=None),
        ) as mark_failed,
    ):
        with pytest.raises(SoftTimeLimitExceeded):
            execute_review_job_task.run(review_job_id=123)

        mark_failed.assert_awaited_once()
        job_id, message = mark_failed.await_args.args
        assert job_id == 123
        assert "soft time limit" in message.lower()


def test_transient_error_exhausted_persists_failed_status():
    with (
        patch(
            "app.tasks.review_jobs.execute_review_job_by_id",
            new=AsyncMock(side_effect=httpx.ConnectError("boom")),
        ),
        patch(
            "app.tasks.review_jobs.mark_review_job_failed_by_id",
            new=AsyncMock(return_value=None),
        ) as mark_failed,
        patch.object(execute_review_job_task, "max_retries", 0),
    ):
        with pytest.raises(httpx.ConnectError):
            execute_review_job_task.run(review_job_id=456)

        mark_failed.assert_awaited_once()
        job_id, message = mark_failed.await_args.args
        assert job_id == 456
        assert "retries exhausted" in message.lower()


def test_abandoned_jobs_task_calls_service():
    with patch(
        "app.tasks.review_jobs.mark_abandoned_jobs_as_failed",
        new=AsyncMock(return_value=2),
    ) as reclaim:
        result = mark_abandoned_jobs.run()

        reclaim.assert_awaited_once()
        assert result == {"cleaned": 2}