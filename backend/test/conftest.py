import pytest  # pyright: ignore[reportMissingImports]

from app.core.celery_app import celery_app


@pytest.fixture(autouse=True)
def celery_eager_mode():
    """Run tasks in-process so tests do not need RabbitMQ."""
    celery_app.conf.task_always_eager = True
    celery_app.conf.task_eager_propagates = True
    yield
    celery_app.conf.task_always_eager = False
    celery_app.conf.task_eager_propagates = False