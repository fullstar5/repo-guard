from app.core.celery_app import celery_app



@celery_app.task(name="app.tasks.debug.hello")
def hello() -> str:
    message = "hello from celery worker"
    print(message)
    return message


@celery_app.task(name="app.tasks.debug.add")
def add(x: int, y: int) -> int:
    result = x + y
    print(f"add task: {x} + {y} = {result}")
    return result