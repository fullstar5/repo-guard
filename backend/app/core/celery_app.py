import logging

from celery import Celery  # pyright: ignore[reportMissingImports]
from celery.signals import setup_logging  # pyright: ignore[reportMissingImports]

from app.core.config import get_settings




settings = get_settings()

celery_app = Celery(
    "repo_guard",
    broker=settings.rabbitmq_url,
    backend=settings.celery_result_backend,
    include=[
        "app.tasks.debug",   # demo practice
        "app.tasks.review_jobs",   # review code job
        "app.tasks.github_webhooks",   # sync PR and files, enqueue review task when github call
    ],
)

celery_app.conf.update(
    task_default_queue="default",
    task_serializer="json",
    accept_content=["json"],
    result_serializer="json",
    timezone="UTC",
    enable_utc=True,
    task_track_started=True,
    task_acks_late=True,   # acknowledge after task execution so crashed workers can re-deliver
    worker_prefetch_multiplier=1,
    broker_connection_retry_on_startup=True,
    broker_heartbeat=None,
    broker_pool_limit=1,
    beat_schedule={
        "reclaim-stale-review-jobs": {
            "task": "app.tasks.review_jobs.mark_abandoned_jobs_as_failed",
            "schedule": settings.celery_task_reclaim_interval_seconds,
        }
    }
)


@setup_logging.connect
def configure_celery_logging(**_kwargs) -> None:
    """Install a single-line log format for worker and beat processes.

    Args:
        **_kwargs: Celery signal arguments. Unused.

    Returns:
        None.
    """
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)s [%(name)s] %(message)s",
        force=True,
    )