import asyncio
import logging

import httpx  # pyright: ignore[reportMissingImports]
from app.core.celery_app import celery_app
from app.core.config import get_settings
from app.services.review_jobs import (
    _format_review_job_error,
    execute_review_job_by_id,
    mark_abandoned_jobs_as_failed,
    mark_review_job_failed_by_id,
)
from billiard.exceptions import (  # pyright: ignore[reportMissingImports]
    SoftTimeLimitExceeded,  # pyright: ignore[reportMissingImports]
)

settings = get_settings()
logger = logging.getLogger(__name__)


TRANSIENT_TASK_ERRORS = (
    httpx.HTTPError,
    httpx.TimeoutException,
    OSError,
)


def _retry_countdown(next_retry: int) -> int:
    """Compute the wait before the next whole-task retry.

    Args:
        next_retry: 1-based retry number about to be scheduled.

    Returns:
        Seconds to wait, doubling from the configured base and capped at the
        configured maximum.
    """
    delay = settings.celery_task_retry_backoff_seconds * (2 ** max(next_retry - 1, 0))
    return min(delay, settings.celery_task_retry_backoff_max)   # no more than 300 sec waiting time



@celery_app.task(
    bind=True,   # so can use self.retry() and self.request.retries
    name="app.tasks.review_jobs.execute_review_job",
    max_retries=settings.celery_task_max_retries,
    soft_time_limit=settings.celery_task_soft_time_limit,
    time_limit=settings.celery_task_time_limit,
)
def execute_review_job_task(self, review_job_id: int) -> dict[str, object]:
    """Run one review job inside a Celery worker process.

    Args:
        review_job_id: Local review job id from the queue message.

    Returns:
        The job id and its status, or ``missing`` when the row is gone.

    Raises:
        SoftTimeLimitExceeded: The job exceeded one hour and the single
        whole-job retry was already used.
        Exception: A non-retryable failure after the job is marked failed.
        Retry: Celery should run the task again after a transient error or
        the first soft timeout.
    """
    logger.info(
        "Starting review job task review_job_id=%s, task_id=%s, retry=%s",
        review_job_id,
        self.request.id,
        self.request.retries,
    )

    # successful path
    try:
        review_job = asyncio.run(execute_review_job_by_id(review_job_id))
        if review_job is None:
            return {
                "review_job_id": review_job_id,
                "status": "missing",
            }

        logger.info(
            "Finish review job task review_job_id=%s, status=%s",
            review_job.id,
            review_job.status.value,
        )

        return {
            "review_job_id": review_job.id,
            "status": review_job.status.value,
        }

    except SoftTimeLimitExceeded as exc:
        message = (
            f"Review job exceeded soft time limit "
            f"({settings.celery_task_soft_time_limit}s)."
        )

        # First 1h timeout: rerun the whole job. Do not mark failed,
        # or execute_review_job_by_id will skip the retry.
        if self.request.retries < 1:
            logger.warning(
                "Retry whole review job %s after soft time limit "
                "(task_id=%s, retry=%s)",
                review_job_id,
                self.request.id,
                self.request.retries,
            )
            raise self.retry(exc=exc, countdown=_retry_countdown(1))

        try:
            asyncio.run(mark_review_job_failed_by_id(review_job_id, message))
        except Exception:
            logger.exception("Failed to persist soft-timeout failure for review_job_id=%s", review_job_id)
        logger.error(
            "review job %s exceeded soft time limit after whole-job retry "
            "(task_id=%s, retry=%s)",
            review_job_id,
            self.request.id,
            self.request.retries,
        )
        raise

    except TRANSIENT_TASK_ERRORS as exc:
        next_retry = self.request.retries + 1

        if next_retry > self.max_retries:
            message = (
                f"Task-level retries exhausted after "
                f"{self.max_retries} attempts: {_format_review_job_error(exc=exc)}"
            )
            asyncio.run(mark_review_job_failed_by_id(review_job_id, message))
            logger.exception("Review job %s exhausted task-level retries.", review_job_id)
            raise
        
        countdown = _retry_countdown(next_retry)
        logger.warning(
            "Retry review job %s in %ss due to transient task error: %s",
            review_job_id,
            countdown,
            exc,
        )
        raise self.retry(exc=exc, countdown=countdown)


    except Exception as exc:
        message = f"Worker task failed before review completion: {_format_review_job_error(exc=exc)}"
        asyncio.run(mark_review_job_failed_by_id(review_job_id, message))
        logger.exception("Review job %s failed in Celery task wrapper.", review_job_id)
        raise



@celery_app.task(
    name="app.tasks.review_jobs.mark_abandoned_jobs_as_failed",
    soft_time_limit=30,
    time_limit=45,
)
def mark_abandoned_jobs() -> dict[str, int]:
    """Mark processing jobs that have not updated within the stale threshold.

    Returns:
        ``{"cleaned": n}`` where ``n`` is how many jobs were marked failed.
    """
    logger.info("Starting stale review job reclaim task")
    failed = asyncio.run(mark_abandoned_jobs_as_failed())
    logger.info("Finished stale review jobs reclaim task, cleaned=%s", failed)
    return {"cleaned": failed}