from sqlalchemy import delete  # pyright: ignore[reportMissingImports]
from sqlalchemy.dialects.postgresql import insert  # pyright: ignore[reportMissingImports]
from sqlalchemy.ext.asyncio import AsyncSession  # pyright: ignore[reportMissingImports]

from app.models.github_webhook_event import GitHubWebhookEvent



async def register_github_webhook_event(
    db: AsyncSession,
    *,
    delivery_id: str,
    event_name: str,
    action: str | None,
    github_repo_id: int | None,
    pull_request_number: int | None,
) -> bool:
    """
    service that register github webhook event atomically, avoid concurrent duplicates
    Return False means delivery has been accepted
    """

    statement = (
        insert(GitHubWebhookEvent).values(
            delivery_id=delivery_id,
            event_name=event_name,
            action=action,
            github_repo_id=github_repo_id,
            pull_request_number=pull_request_number,
        ).on_conflict_do_nothing(
            index_elements=[GitHubWebhookEvent.delivery_id],   # use delivery id to check duplicates
        ).returning(GitHubWebhookEvent.id)
    )

    result = await db.execute(statement)
    event_id = result.scalar_one_or_none()
    await db.commit()

    return event_id is not None



async def delete_github_webhook_event(
    db: AsyncSession,
    delivery_id: str,
) -> None:
    """
    service that remove github webhook when rabbitmq publish failed, so github can retry 
    """
    await db.execute(
        delete(GitHubWebhookEvent).where(GitHubWebhookEvent.delivery_id == delivery_id)
    )
    await db.commit()