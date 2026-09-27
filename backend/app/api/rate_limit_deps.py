import hashlib
import hmac
import ipaddress
import logging

import httpx  # pyright: ignore[reportMissingImports]
from fastapi import Depends, HTTPException, Request, status  # pyright: ignore[reportMissingImports]

from app.api.deps import get_current_user
from app.core.config import get_settings
from app.models.user import User
from app.services.rate_limit import (
    RateLimitBackendError,
    RateLimitRule,
    check_rate_limits,
)


logger = logging.getLogger(__name__)
settings = get_settings()
RATE_LIMIT_KEY_PREFIX = "repo-guard:rate-limit:v1"


def _normalized_ip(value: str | None) -> str | None:
    """Normalize one IP string.

    Args:
        value: Raw address, or None.

    Returns:
        The compressed IP, or None when the value is empty or not an IP.
    """
    if not value:
        return None

    try:
        return ipaddress.ip_address(value.strip()).compressed
    except ValueError:
        return None


def get_client_ip(request: Request) -> str:
    """Resolve the nearest untrusted client address.

    Reading from the right prevents a caller-supplied leftmost X-Forwarded-For
    value from bypassing limits when trusted proxies append their own entries.

    Args:
        request: Incoming request.

    Returns:
        A normalized IP, or ``"unknown"`` when none can be read.
    """
    forwarded_for = request.headers.get("x-forwarded-for")
    trusted_hops = settings.rate_limit_trusted_proxy_hops

    if forwarded_for and trusted_hops > 0:
        addresses = [
            item.strip()
            for item in forwarded_for.split(",")
            if item.strip()
        ]
        if addresses:
            candidate_index = -min(trusted_hops, len(addresses))
            forwarded_ip = _normalized_ip(addresses[candidate_index])
            if forwarded_ip:
                return forwarded_ip

    direct_ip = _normalized_ip(
        request.client.host if request.client is not None else None
    )
    return direct_ip or "unknown"


def _private_identifier(value: str) -> str:
    """Hash a client identifier so raw IP addresses are not stored in Redis.

    Args:
        value: IP address or other client key.

    Returns:
        HMAC-SHA256 hex digest keyed by the JWT secret.
    """
    return hmac.new(
        settings.jwt_secret_key.encode(),
        f"rate-limit:{value}".encode(),
        hashlib.sha256,
    ).hexdigest()


async def _enforce(
    request: Request,
    rules: tuple[RateLimitRule, ...],
) -> None:
    """Apply rate-limit rules, or return immediately when limiting is off.

    Args:
        request: Incoming request; its app state holds the HTTP client.
        rules: Fixed-window buckets to increment together.

    Returns:
        None when the request is allowed.

    Raises:
        HTTPException: 429 when a bucket is full, 503 when Redis cannot decide.
    """
    if not settings.rate_limit_enabled:
        return

    try:
        http_client: httpx.AsyncClient = request.app.state.http_client
        decision = await check_rate_limits(http_client, rules)
    except (AttributeError, RateLimitBackendError) as exc:
        logger.exception("Rate limit backend unavailable")
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Rate limit service unavailable",
            headers={"Retry-After": "5"},
        ) from exc

    if not decision.allowed:
        raise HTTPException(
            status_code=status.HTTP_429_TOO_MANY_REQUESTS,
            detail="Rate limit exceeded",
            headers={
                "Retry-After": str(decision.retry_after_seconds),
            },
        )


async def limit_oauth_requests(request: Request) -> None:
    """Limit GitHub login and callback requests by client IP.

    Args:
        request: Incoming OAuth request.

    Returns:
        None when the request is allowed.
    """
    client_ip_hash = _private_identifier(get_client_ip(request))
    await _enforce(
        request,
        (
            RateLimitRule(
                key=f"{RATE_LIMIT_KEY_PREFIX}:oauth:ip:{client_ip_hash}",
                limit=settings.rate_limit_oauth_requests,
                window_seconds=settings.rate_limit_oauth_window_seconds,
            ),
        ),
    )


def _sync_user_rule(user_id: int) -> RateLimitRule:
    """Build the per-user sync bucket shared by repository, PR, and file sync.

    Args:
        user_id: Local user id.

    Returns:
        The user-wide sync rule.
    """
    return RateLimitRule(
        key=f"{RATE_LIMIT_KEY_PREFIX}:sync:user:{user_id}",
        limit=settings.rate_limit_sync_user_requests,
        window_seconds=settings.rate_limit_sync_user_window_seconds,
    )


def _sync_object_rule(
    *,
    user_id: int,
    object_type: str,
    object_id: int,
) -> RateLimitRule:
    """Build a per-object sync bucket.

    Args:
        user_id: Local user id.
        object_type: Bucket name, such as ``repository`` or ``pull-request``.
        object_id: Local id of that object.

    Returns:
        The object-specific sync rule.
    """
    return RateLimitRule(
        key=(
            f"{RATE_LIMIT_KEY_PREFIX}:sync:user:{user_id}:"
            f"{object_type}:{object_id}"
        ),
        limit=settings.rate_limit_sync_object_requests,
        window_seconds=settings.rate_limit_sync_object_window_seconds,
    )


async def limit_repository_sync(
    request: Request,
    current_user: User = Depends(get_current_user),
) -> None:
    """Limit how often one user can sync their repository list.

    Args:
        request: Incoming sync request.
        current_user: Authenticated user.

    Returns:
        None when the request is allowed.
    """
    await _enforce(request, (_sync_user_rule(current_user.id),))


async def limit_pull_request_sync(
    repository_id: int,
    request: Request,
    current_user: User = Depends(get_current_user),
) -> None:
    """Limit pull-request sync for one user and one repository.

    Args:
        repository_id: Local repository id.
        request: Incoming sync request.
        current_user: Authenticated user.

    Returns:
        None when the request is allowed.
    """
    await _enforce(
        request,
        (
            _sync_user_rule(current_user.id),
            _sync_object_rule(
                user_id=current_user.id,
                object_type="repository",
                object_id=repository_id,
            ),
        ),
    )


async def limit_file_sync(
    pull_request_id: int,
    request: Request,
    current_user: User = Depends(get_current_user),
) -> None:
    """Limit file sync for one user and one pull request.

    Args:
        pull_request_id: Local pull request id.
        request: Incoming sync request.
        current_user: Authenticated user.

    Returns:
        None when the request is allowed.
    """
    await _enforce(
        request,
        (
            _sync_user_rule(current_user.id),
            _sync_object_rule(
                user_id=current_user.id,
                object_type="pull-request",
                object_id=pull_request_id,
            ),
        ),
    )


async def limit_review_creation(
    pull_request_id: int,
    request: Request,
    current_user: User = Depends(get_current_user),
) -> None:
    """Limit review-job creation for one user and one pull request.

    Args:
        pull_request_id: Local pull request id.
        request: Incoming create request.
        current_user: Authenticated user.

    Returns:
        None when the request is allowed.
    """
    await _enforce(
        request,
        (
            RateLimitRule(
                key=f"{RATE_LIMIT_KEY_PREFIX}:review:user:{current_user.id}",
                limit=settings.rate_limit_review_user_requests,
                window_seconds=settings.rate_limit_review_user_window_seconds,
            ),
            RateLimitRule(
                key=(
                    f"{RATE_LIMIT_KEY_PREFIX}:review:user:{current_user.id}:"
                    f"pull-request:{pull_request_id}"
                ),
                limit=settings.rate_limit_review_object_requests,
                window_seconds=settings.rate_limit_review_object_window_seconds,
            ),
        ),
    )
