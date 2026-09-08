import asyncio
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from fastapi import HTTPException

from app.api.rate_limit_deps import (
    _enforce,
    get_client_ip,
    limit_review_creation,
)
from app.services.rate_limit import (
    RATE_LIMIT_SCRIPT,
    RateLimitBackendError,
    RateLimitDecision,
    RateLimitRule,
    check_rate_limits,
)


def _request() -> MagicMock:
    request = MagicMock()
    request.app.state.http_client = AsyncMock()
    request.headers = {}
    request.client.host = "127.0.0.1"
    return request


def test_check_rate_limits_uses_one_atomic_eval_for_multiple_rules():
    response = MagicMock()
    response.json.return_value = {"result": [1, 0]}
    http_client = AsyncMock()
    http_client.post.return_value = response
    rules = (
        RateLimitRule("rate:user:7", 5, 60),
        RateLimitRule("rate:user:7:pr:9", 2, 600),
    )

    decision = asyncio.run(check_rate_limits(http_client, rules))

    assert decision == RateLimitDecision(
        allowed=True,
        retry_after_seconds=0,
    )
    command = http_client.post.await_args.kwargs["json"]
    assert command == [
        "EVAL",
        RATE_LIMIT_SCRIPT,
        "2",
        "rate:user:7",
        "rate:user:7:pr:9",
        "5",
        "60000",
        "2",
        "600000",
    ]


def test_check_rate_limits_rounds_retry_after_up():
    response = MagicMock()
    response.json.return_value = {"result": [0, 1501]}
    http_client = AsyncMock()
    http_client.post.return_value = response

    decision = asyncio.run(
        check_rate_limits(
            http_client,
            (RateLimitRule("rate:user:7", 1, 60),),
        )
    )

    assert decision.allowed is False
    assert decision.retry_after_seconds == 2


def test_check_rate_limits_rejects_malformed_backend_response():
    response = MagicMock()
    response.json.return_value = {"result": "unexpected"}
    http_client = AsyncMock()
    http_client.post.return_value = response

    with pytest.raises(RateLimitBackendError):
        asyncio.run(
            check_rate_limits(
                http_client,
                (RateLimitRule("rate:user:7", 1, 60),),
            )
        )


def test_enforce_returns_429_and_retry_after_when_limit_is_exceeded():
    request = _request()
    with (
        patch(
            "app.api.rate_limit_deps.settings.rate_limit_enabled",
            True,
        ),
        patch(
            "app.api.rate_limit_deps.check_rate_limits",
            new=AsyncMock(
                return_value=RateLimitDecision(
                    allowed=False,
                    retry_after_seconds=17,
                )
            ),
        ),
        pytest.raises(HTTPException) as exc_info,
    ):
        asyncio.run(
            _enforce(
                request,
                (RateLimitRule("rate:user:7", 1, 60),),
            )
        )

    assert exc_info.value.status_code == 429
    assert exc_info.value.headers == {"Retry-After": "17"}


def test_enforce_fails_closed_when_upstash_is_unavailable():
    request = _request()
    with (
        patch(
            "app.api.rate_limit_deps.settings.rate_limit_enabled",
            True,
        ),
        patch(
            "app.api.rate_limit_deps.check_rate_limits",
            new=AsyncMock(side_effect=RateLimitBackendError("unavailable")),
        ),
        pytest.raises(HTTPException) as exc_info,
    ):
        asyncio.run(
            _enforce(
                request,
                (RateLimitRule("rate:user:7", 1, 60),),
            )
        )

    assert exc_info.value.status_code == 503
    assert exc_info.value.headers == {"Retry-After": "5"}


def test_enforce_skips_redis_when_disabled_for_local_development():
    request = _request()
    check = AsyncMock()
    with (
        patch(
            "app.api.rate_limit_deps.settings.rate_limit_enabled",
            False,
        ),
        patch("app.api.rate_limit_deps.check_rate_limits", new=check),
    ):
        asyncio.run(
            _enforce(
                request,
                (RateLimitRule("rate:user:7", 1, 60),),
            )
        )

    check.assert_not_awaited()


def test_client_ip_uses_configured_trusted_proxy_hops():
    request = _request()
    request.headers = {
        "x-forwarded-for": "203.0.113.9, 198.51.100.20",
    }

    with patch(
        "app.api.rate_limit_deps.settings.rate_limit_trusted_proxy_hops",
        1,
    ):
        assert get_client_ip(request) == "198.51.100.20"

    with patch(
        "app.api.rate_limit_deps.settings.rate_limit_trusted_proxy_hops",
        2,
    ):
        assert get_client_ip(request) == "203.0.113.9"


def test_review_limit_combines_user_and_pull_request_buckets():
    request = _request()
    user = MagicMock()
    user.id = 7
    check = AsyncMock(
        return_value=RateLimitDecision(
            allowed=True,
            retry_after_seconds=0,
        )
    )

    with (
        patch(
            "app.api.rate_limit_deps.settings.rate_limit_enabled",
            True,
        ),
        patch("app.api.rate_limit_deps.check_rate_limits", new=check),
    ):
        asyncio.run(limit_review_creation(9, request, user))

    rules = check.await_args.args[1]
    assert len(rules) == 2
    assert rules[0].key.endswith(":review:user:7")
    assert rules[1].key.endswith(":review:user:7:pull-request:9")
