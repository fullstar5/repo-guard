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
    """Record one GitHub delivery if it has not been accepted before.

    Args:
        db: Open async session. This function commits.
        delivery_id: ``X-GitHub-Delivery`` value.
        event_name: ``X-GitHub-Event`` value.
        action: Payload action, such as ``opened`` or ``synchronize``.
        github_repo_id: GitHub repository id, when present.
        pull_request_number: Pull request number, when present.

    Returns:
        True when this call inserted the delivery. False when that delivery
        id was already stored.
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
    """Delete a delivery record so GitHub can retry after a broker failure.

    Args:
        db: Open async session. This function commits.
        delivery_id: ``X-GitHub-Delivery`` value to remove.

    Returns:
        None.
    """
    await db.execute(
        delete(GitHubWebhookEvent).where(GitHubWebhookEvent.delivery_id == delivery_id)
    )
    await db.commit()