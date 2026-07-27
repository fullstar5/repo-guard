import asyncio

from app.core.celery_app import celery_app
from app.services.review_jobs import execute_review_job_by_id




@celery_app.task(name="app.tasks.review_jobs.execute_review_job")
def execute_review_job_task(review_job_id: int) -> dict[str, object]:
    review_job = asyncio.run(execute_review_job_by_id(review_job_id))

    if review_job is None:
        return {
            "review_job_id": review_job_id,
            "status": "missing",
        }

    return {
        "review_job_id": review_job_id,
        "status": review_job.status.value,
    }