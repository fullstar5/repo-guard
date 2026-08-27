import asyncio
import logging

from app.core.celery_app import celery_app
from app.services.github_webhook_pipeline import process_github_pull_request_event


logger = logging.getLogger(__name__)


@celery_app.task(name="app.tasks.github_webhooks.process_github_pull_request_webhook")
def process_github_pull_request_webhook(payload: dict) -> dict:
    """Background task: sync PR and files, then enqueue the existing review task."""
    delivery = (payload.get("pull_request") or {}).get("url")
    logger.info("Starting webhook pipeline task pull_request=%s", delivery)
    asyncio.run(process_github_pull_request_event(payload))

    return {"ok": True}
