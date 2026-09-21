import asyncio
from unittest.mock import AsyncMock, patch

import httpx  # pyright: ignore[reportMissingImports]
import pytest  # pyright: ignore[reportMissingImports]
from billiard.exceptions import SoftTimeLimitExceeded  # pyright: ignore[reportMissingImports]

from app.services.review_jobs import _review_content_with_retries
from app.services.review_provider import ReviewResult


def _http_status_error(status_code: int) -> httpx.HTTPStatusError:
    request = httpx.Request("POST", "https://openrouter.ai/api/v1/chat/completions")
    response = httpx.Response(status_code, request=request)
    return httpx.HTTPStatusError(
        f"HTTP {status_code}",
        request=request,
        response=response,
    )


def test_http_retries_sleep_35s_between_attempts():
    sleeps: list[float] = []

    async def fake_sleep(seconds: float) -> None:
        sleeps.append(seconds)

    provider = AsyncMock()
    provider.review_content = AsyncMock(side_effect=_http_status_error(429))

    async def run() -> None:
        with patch("app.services.review_jobs.asyncio.sleep", new=fake_sleep):
            await _review_content_with_retries(
                provider,
                "payload",
                request_label="pack 1",
                attempt_count=3,
            )

    with pytest.raises(httpx.HTTPStatusError):
        asyncio.run(run())

    assert provider.review_content.await_count == 3
    assert sleeps == [35, 35]
    assert sum(sleeps) > 60


def test_http_retry_succeeds_after_one_wait():
    sleeps: list[float] = []

    async def fake_sleep(seconds: float) -> None:
        sleeps.append(seconds)

    provider = AsyncMock()
    provider.review_content = AsyncMock(
        side_effect=[
            _http_status_error(500),
            ReviewResult(summary="ok", findings=[]),
        ]
    )

    async def run() -> ReviewResult:
        with patch("app.services.review_jobs.asyncio.sleep", new=fake_sleep):
            return await _review_content_with_retries(
                provider,
                "payload",
                request_label="pack 1",
                attempt_count=3,
            )

    result = asyncio.run(run())
    assert result.summary == "ok"
    assert sleeps == [35]


def test_timeout_is_not_retried():
    provider = AsyncMock()
    provider.review_content = AsyncMock(side_effect=TimeoutError())

    with patch(
        "app.services.review_jobs.asyncio.sleep",
        new=AsyncMock(side_effect=AssertionError("timeout must not sleep")),
    ):
        with pytest.raises(TimeoutError):
            asyncio.run(
                _review_content_with_retries(
                    provider,
                    "payload",
                    request_label="pack 1",
                    attempt_count=3,
                )
            )

    assert provider.review_content.await_count == 1


def test_soft_time_limit_is_not_retried():
    provider = AsyncMock()
    provider.review_content = AsyncMock(side_effect=SoftTimeLimitExceeded())

    with pytest.raises(SoftTimeLimitExceeded):
        asyncio.run(
            _review_content_with_retries(
                provider,
                "payload",
                request_label="pack 1",
                attempt_count=3,
            )
        )

    assert provider.review_content.await_count == 1
