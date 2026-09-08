from dataclasses import dataclass
from math import ceil

import httpx  # pyright: ignore[reportMissingImports]

from app.core.config import get_settings


settings = get_settings()

RATE_LIMIT_SCRIPT = """
local allowed = 1
local retry_after_ms = 0

for index, key in ipairs(KEYS) do
    local argument_index = (index - 1) * 2
    local limit = tonumber(ARGV[argument_index + 1])
    local window_ms = tonumber(ARGV[argument_index + 2])
    local count = redis.call("INCR", key)

    if count == 1 then
        redis.call("PEXPIRE", key, window_ms)
    end

    local ttl_ms = redis.call("PTTL", key)
    if ttl_ms < 0 then
        redis.call("PEXPIRE", key, window_ms)
        ttl_ms = window_ms
    end

    if count > limit then
        allowed = 0
        if ttl_ms > retry_after_ms then
            retry_after_ms = ttl_ms
        end
    end
end

return {allowed, retry_after_ms}
""".strip()


@dataclass(frozen=True)
class RateLimitRule:
    key: str
    limit: int
    window_seconds: int


@dataclass(frozen=True)
class RateLimitDecision:
    allowed: bool
    retry_after_seconds: int


class RateLimitBackendError(RuntimeError):
    """Raised when Upstash cannot provide a trustworthy limit decision."""


async def check_rate_limits(
    http_client: httpx.AsyncClient,
    rules: tuple[RateLimitRule, ...],
) -> RateLimitDecision:
    """Atomically increment and evaluate one or more fixed-window buckets."""
    if not rules:
        raise ValueError("At least one rate limit rule is required")

    keys = [rule.key for rule in rules]
    arguments: list[str] = []
    for rule in rules:
        if rule.limit <= 0 or rule.window_seconds <= 0:
            raise ValueError("Rate limit and window must be greater than zero")
        arguments.extend([str(rule.limit), str(rule.window_seconds * 1000)])

    command = [
        "EVAL",
        RATE_LIMIT_SCRIPT,
        str(len(keys)),
        *keys,
        *arguments,
    ]

    try:
        response = await http_client.post(
            settings.upstash_redis_rest_url.rstrip("/"),
            headers={
                "Authorization": f"Bearer {settings.upstash_redis_rest_token}",
            },
            json=command,
            timeout=settings.rate_limit_timeout_seconds,
        )
        response.raise_for_status()
        payload = response.json()
        if not isinstance(payload, dict):
            raise ValueError("Unexpected Upstash rate limit payload")
        result = payload.get("result")
        if not isinstance(result, list) or len(result) != 2:
            raise ValueError("Unexpected Upstash rate limit response")

        allowed = int(result[0]) == 1
        retry_after_ms = max(0, int(result[1]))
    except (httpx.HTTPError, TypeError, ValueError, KeyError) as exc:
        raise RateLimitBackendError(
            "Upstash rate limit check failed"
        ) from exc

    return RateLimitDecision(
        allowed=allowed,
        retry_after_seconds=(
            0 if allowed else max(1, ceil(retry_after_ms / 1000))
        ),
    )
