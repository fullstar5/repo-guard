import logging

from fastapi import (  # pyright: ignore[reportMissingImports]
    APIRouter,
    Depends,
    HTTPException,
    Request,
    status,
)
from sqlalchemy.ext.asyncio import AsyncSession  # pyright: ignore[reportMissingImports]

from app.api.deps import get_db
from app.core.config import get_settings
from app.services.github_webhook import (
    log_github_webhook_event,
    parse_github_payload,
    summarize_github_event,
    verify_github_signature,
)
from app.services.github_webhook_events import (
    delete_github_webhook_event,
    register_github_webhook_event,
)
from app.tasks.github_webhooks import process_github_pull_request_webhook


router = APIRouter(tags=["webhooks"])
settings = get_settings()
logger = logging.getLogger(__name__)


@router.post("/webhooks/github")
async def github_webhook(
    request: Request,
    db: AsyncSession = Depends(get_db),
):
    """
    verify and register a github delivery, then dispatch supported events
    AI events and github sync remain outside HTTP request
    """
    body = await request.body()
    signature = request.headers.get("X-Hub-Signature-256")
    event_name = request.headers.get("X-GitHub-Event")
    delivery_id = request.headers.get("X-GitHub-Delivery")


    if not verify_github_signature(
        secret=settings.github_webhook_secret,
        body=body,
        signature_header=signature,
    ):
        logger.warning(
            "GitHub webhook rejected delivery_id=%s (invalid signature)",
            delivery_id,
        )
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid webhook signature",
        )


    try:
        payload = parse_github_payload(body)
    except ValueError as exc:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=str(exc),
        ) from exc
    summary = summarize_github_event(
        event_name=event_name,
        delivery_id=delivery_id,
        payload=payload,
    )
    log_github_webhook_event(summary)

    # Ping and unsupported events must still return 2xx.
    if not summary["handled"]:
        return {
            "accepted": True,
            "delivery_id": delivery_id,
            "event": summary["event"],
            "action": summary["action"],
            "handled": False,
            "duplicate": False,
            "dispatched": False,
        }

    if not delivery_id:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Missing X-GitHub-Delivery header",
        )

    # if github delivery already exist
    is_new_delivery = await register_github_webhook_event(
        db,
        delivery_id=delivery_id,
        event_name=event_name or "unknown",
        action=summary["action"],
        github_repo_id=summary["github_repo_id"],
        pull_request_number=summary["pr_number"],
    )
    if not is_new_delivery:
        logger.info(
            "Skip duplicate GitHub delivery delivery_id=%s",
            delivery_id,
        )
        return {
            "accepted": True,
            "delivery_id": delivery_id,
            "event": summary["event"],
            "action": summary["action"],
            "handled": True,
            "duplicate": True,
            "dispatched": False,
        }
    
    try:
        process_github_pull_request_webhook.delay(payload)
    except Exception as exc:
        # if rabbitmq publihs failed or enqueue failed
        await delete_github_webhook_event(db, delivery_id)
        logger.exception(
            "Failed to enqueue GitHub delivery delivery_id=%s",
            delivery_id,
        )
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Failed to enqueue webhook event",
        ) from exc

    return {
        "accepted": True,
        "delivery_id": delivery_id,
        "event": summary["event"],
        "action": summary["action"],
        "handled": True,
        "duplicate": False,
        "dispatched": True,
    }