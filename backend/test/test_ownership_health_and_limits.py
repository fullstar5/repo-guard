import asyncio
from unittest.mock import AsyncMock, MagicMock, patch

import pytest  # pyright: ignore[reportMissingImports]
from pydantic import ValidationError  # pyright: ignore[reportMissingImports]

from app.api.health import check_postgres, check_redis
from app.api.rate_limit_deps import (
    limit_file_sync,
    limit_oauth_requests,
    limit_pull_request_sync,
    limit_repository_sync,
)
from app.core.config import Settings
from app.services.github_pr_files import get_PR_file_for_user
from app.services.review_jobs import (
    get_pull_request_for_user,
    get_review_job_with_findings_for_user,
)
from helpers import async_cm, scalar_result


def _values(**overrides) -> dict:
    values = {
        "neon_postgres_url": "postgresql://user:password@database.example.com/codeguard",
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
    values.update(overrides)
    return values


def _request() -> MagicMock:
    request = MagicMock()
    request.app.state.http_client = AsyncMock()
    request.headers = {}
    request.client.host = "203.0.113.8"
    return request


def _compiled_params(statement) -> dict:
    compiled = statement.compile(compile_kwargs={"render_postcompile": True})
    return dict(compiled.params)


def test_review_and_file_queries_bind_the_caller_user_id():
    db = AsyncMock()
    db.execute = AsyncMock(return_value=scalar_result(None))

    async def _inner():
        await get_review_job_with_findings_for_user(db, review_job_id=15, user_id=7)
        await get_pull_request_for_user(db, pull_request_id=4, user_id=7)
        await get_PR_file_for_user(db, pull_request_id=4, file_id=9, user_id=7)

    asyncio.run(_inner())
    statements = [call.args[0] for call in db.execute.await_args_list]
    assert len(statements) == 3
    for statement in statements:
        params = _compiled_params(statement)
        assert 7 in params.values()
        sql = str(statement.compile(compile_kwargs={"render_postcompile": True})).lower()
        assert "user_id" in sql


def test_oauth_limit_hashes_the_client_ip():
    request = _request()
    check = AsyncMock()
    with (
        patch("app.api.rate_limit_deps.settings.rate_limit_enabled", True),
        patch("app.api.rate_limit_deps.check_rate_limits", new=check),
    ):
        asyncio.run(limit_oauth_requests(request))

    key = check.await_args.args[1][0].key
    assert key.endswith(":oauth:ip:") is False
    assert ":oauth:ip:" in key
    assert "203.0.113.8" not in key


def test_sync_limits_use_user_and_object_buckets():
    request = _request()
    user = MagicMock()
    user.id = 7
    check = AsyncMock()
    with (
        patch("app.api.rate_limit_deps.settings.rate_limit_enabled", True),
        patch("app.api.rate_limit_deps.check_rate_limits", new=check),
    ):
        asyncio.run(limit_repository_sync(request, user))
        asyncio.run(limit_pull_request_sync(9, request, user))
        asyncio.run(limit_file_sync(4, request, user))

    repo_keys = [rule.key for rule in check.await_args_list[0].args[1]]
    pr_keys = [rule.key for rule in check.await_args_list[1].args[1]]
    file_keys = [rule.key for rule in check.await_args_list[2].args[1]]
    assert repo_keys == ["repo-guard:rate-limit:v1:sync:user:7"]
    assert "repo-guard:rate-limit:v1:sync:user:7:repository:9" in pr_keys
    assert "repo-guard:rate-limit:v1:sync:user:7:pull-request:4" in file_keys


def test_production_settings_reject_short_secrets_and_local_brokers():
    with pytest.raises(ValidationError) as short_secret:
        Settings(
            _env_file=None,
            environment="production",
            **_values(jwt_secret_key="short", github_webhook_secret="short"),
        )
    message = str(short_secret.value)
    assert "JWT_SECRET_KEY" in message
    assert "GITHUB_WEBHOOK_SECRET" in message

    with pytest.raises(ValidationError) as local_db:
        Settings(
            _env_file=None,
            environment="production",
            **_values(
                neon_postgres_url="postgresql://user:pass@localhost/codeguard",
                rabbitmq_url="amqp://guest:guest@rabbitmq:5672//",
            ),
        )
    text = str(local_db.value)
    assert "NEON_POSTGRES_URL" in text
    assert "RABBITMQ_URL" in text


def test_non_production_still_rejects_non_positive_rate_limits():
    with pytest.raises(ValidationError):
        Settings(
            _env_file=None,
            environment="development",
            **_values(
                frontend_url="http://localhost:3000",
                github_redirect_uri="http://localhost:8000/auth/github/callback",
                app_public_url="http://localhost:3000",
                cookie_secure=False,
                rate_limit_enabled=False,
                rate_limit_oauth_requests=0,
            ),
        )


def test_postgres_and_redis_health_report_query_results():
    conn = AsyncMock()
    ok = MagicMock()
    ok.scalar.return_value = 1
    bad = MagicMock()
    bad.scalar.return_value = 0
    conn.execute = AsyncMock(side_effect=[ok, bad])

    with patch("app.api.health.engine") as engine:
        engine.connect.return_value = async_cm(conn)
        assert asyncio.run(check_postgres()) == {"status": "ok"}
        engine.connect.return_value = async_cm(conn)
        assert asyncio.run(check_postgres()) == {"status": "error"}

    http = AsyncMock()
    pong = MagicMock()
    pong.json.return_value = {"result": "PONG"}
    nope = MagicMock()
    nope.json.return_value = {"result": "LOADING"}
    http.post = AsyncMock(side_effect=[pong, nope])
    assert asyncio.run(check_redis(http)) == {"status": "ok"}
    assert asyncio.run(check_redis(http)) == {"status": "error"}
