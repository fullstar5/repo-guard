from celery import Celery  # pyright: ignore[reportMissingImports]

from app.core.config import get_settings




settings = get_settings()

celery_app = Celery(
    "repo_guard",
    broker=settings.rabbitmq_url,
    backend=settings.celery_result_backend,
    include=[
        "app.tasks.debug",   # demo practice
        "app.tasks.review_jobs",   # review code job
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
)


