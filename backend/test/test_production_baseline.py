import asyncio
import json
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from pydantic import ValidationError

from app.api.health import _readiness_response, liveness_check
from app.core.config import Settings


def _settings_values() -> dict[str, object]:
    return {
        "neon_postgres_url": (
            "postgresql://user:password@database.example.com/codeguard"
            "?sslmode=require"
        ),
        "upstash_redis_rest_url": "https://redis.example.com",
        "upstash_redis_rest_token": "redis-token",
        "github_client_id": "github-client-id",
        "github_client_secret": "github-client-secret",
        "github_redirect_uri": "https://app.example.com/api/auth/github/callback",
        "github_webhook_secret": "w" * 32,
        "frontend_url": "https://app.example.com",
        "github_oauth_scope": "read:user user:email repo",
        "oauth_state_cookie_name": "codeguard_oauth_state",
        "cookie_secure": True,
        "jwt_secret_key": "j" * 32,
        "jwt_algorithm": "HS256",
        "access_token_expire_minutes": 60,
        "open_router_api_key": "openrouter-key",
        "app_public_url": "https://app.example.com",
        "rabbitmq_url": "amqps://user:password@rabbitmq.example.com/vhost",
        "rate_limit_enabled": True,
    }


def _request() -> MagicMock:
    request = MagicMock()
    request.app.state.http_client = MagicMock()
    return request


def test_production_settings_accept_secure_deployment_values():
    settings = Settings(
        _env_file=None,
        environment="production",
        **_settings_values(),
    )

    assert settings.environment == "production"
    assert settings.cookie_secure is True


def test_production_settings_reject_localhost_and_insecure_cookie():
    values = _settings_values()
    values.update(
        {
            "frontend_url": "http://localhost:3000",
            "github_redirect_uri": "http://localhost:8000/auth/github/callback",
            "app_public_url": "http://localhost:3000",
            "cookie_secure": False,
        }
    )

    with pytest.raises(ValidationError) as exc_info:
        Settings(
            _env_file=None,
            environment="production",
            **values,
        )

    message = str(exc_info.value)
    assert "FRONTEND_URL must use https" in message
    assert "COOKIE_SECURE must be true" in message


def test_production_settings_require_rate_limiting():
    values = _settings_values()
    values["rate_limit_enabled"] = False

    with pytest.raises(ValidationError) as exc_info:
        Settings(
            _env_file=None,
            environment="production",
            **values,
        )

    assert "RATE_LIMIT_ENABLED must be true" in str(exc_info.value)


def test_liveness_does_not_call_external_dependencies():
    result = asyncio.run(liveness_check())

    assert result == {"status": "ok"}


def test_readiness_is_degraded_when_optional_redis_is_unavailable():
    with (
        patch(
            "app.api.health.check_postgres",
            new=AsyncMock(return_value={"status": "ok"}),
        ),
        patch(
            "app.api.health.check_redis",
            new=AsyncMock(side_effect=RuntimeError("redis unavailable")),
        ),
    ):
        response = asyncio.run(_readiness_response(_request()))

    payload = json.loads(response.body)
    assert response.status_code == 200
    assert payload["status"] == "degraded"
    assert payload["services"]["redis"] == {"status": "error"}


def test_readiness_fails_when_postgres_is_unavailable():
    with (
        patch(
            "app.api.health.check_postgres",
            new=AsyncMock(side_effect=RuntimeError("database unavailable")),
        ),
        patch(
            "app.api.health.check_redis",
            new=AsyncMock(return_value={"status": "ok"}),
        ),
    ):
        response = asyncio.run(_readiness_response(_request()))

    payload = json.loads(response.body)
    assert response.status_code == 503
    assert payload["status"] == "error"
    assert payload["services"]["postgres"] == {"status": "error"}
