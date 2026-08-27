import logging

from fastapi import APIRouter, HTTPException, Request, status

from app.core.config import get_settings
from app.services.github_webhook import (
    log_github_webhook_event,
    parse_github_payload,
    summarize_github_event,
    verify_github_signature,
)




router = APIRouter(tags=["webhooks"])
settings = get_settings()
logger = logging.getLogger(__name__)


@router.post("/webhooks/github")
async def github_webhook(request: Request):
    """receive github events, verify hmac, log, return 2xx"""
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
    return {
        "accepted": True,
        "delivery_id": summary["delivery_id"],
        "event": summary["event"],
        "action": summary["action"],
        "handled": summary["handled"],
    }