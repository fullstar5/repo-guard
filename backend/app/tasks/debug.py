from app.core.celery_app import celery_app



@celery_app.task(name="app.tasks.debug.hello")
def hello() -> str:
    """Print a fixed message so the worker can be checked by hand.

    Returns:
        The printed message.
    """
    message = "hello from celery worker"
    print(message)
    return message


@celery_app.task(name="app.tasks.debug.add")
def add(x: int, y: int) -> int:
    """Add two integers. Used to verify that Celery delivers arguments.

    Args:
        x: First addend.
        y: Second addend.

    Returns:
        ``x + y``.
    """
    result = x + y
    print(f"add task: {x} + {y} = {result}")
    return result