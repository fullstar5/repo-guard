import asyncio
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch

import httpx  # pyright: ignore[reportMissingImports]
import pytest  # pyright: ignore[reportMissingImports]
from fastapi import HTTPException  # pyright: ignore[reportMissingImports]

from app.models.review_job import ReviewJob, ReviewJobStatus
from app.models.user import User
from app.schemas.auth import GitHubAccessTokenResponse, GitHubUserProfile
from app.services.github_oauth import (
    build_github_authorize_url,
    exchange_code_for_access_token,
    fetch_primary_email,
    fetch_github_user,
)
from app.services.github_tokens import GitHubTokenUnavailable
from app.services.github_webhook_pipeline import process_github_pull_request_event
from app.services.openrouter_provider import OpenRouterReviewProvider
from app.services.users import upsert_github_user
from app.tasks.github_webhooks import process_github_pull_request_webhook
from helpers import async_cm, scalar_result


def _client(handler):
    return httpx.AsyncClient(transport=httpx.MockTransport(handler))


async def _pass_github_token(_user_id, _http_client, operation):
    return await operation("gho")


def test_authorize_url_includes_state_and_configured_client():
    url = build_github_authorize_url("abc")
    assert url.startswith("https://github.com/login/oauth/authorize?")
    assert "state=abc" in url
    assert "client_id=" in url


def test_exchange_code_rejects_github_error_payload():
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200,
            json={"error": "bad_verification_code", "error_description": "bad code"},
        )

    async def _inner():
        async with _client(handler) as client:
            await exchange_code_for_access_token(client, "code")

    with pytest.raises(HTTPException) as exc_info:
        asyncio.run(_inner())
    assert exc_info.value.status_code == 400
    assert exc_info.value.detail == "bad code"


def test_fetch_user_and_primary_email_preferences():
    def handler(request: httpx.Request) -> httpx.Response:
        if str(request.url).endswith("/user"):
            return httpx.Response(200, json={"id": 9, "login": "octo", "email": None})
        return httpx.Response(
            200,
            json=[
                {"email": "other@example.com", "primary": False, "verified": True},
                {"email": "primary@example.com", "primary": True, "verified": True},
                {"email": "nope@example.com", "primary": True, "verified": False},
            ],
        )

    async def _inner():
        async with _client(handler) as client:
            user = await fetch_github_user(client, "token")
            email = await fetch_primary_email(client, "token")
            return user, email

    user, email = asyncio.run(_inner())
    assert user.login == "octo"
    assert email == "primary@example.com"


def test_email_endpoint_403_is_optional():
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(403, json={"message": "no"})

    async def _inner():
        async with _client(handler) as client:
            return await fetch_primary_email(client, "token")

    assert asyncio.run(_inner()) is None


def test_upsert_inserts_then_updates_the_same_github_user():
    created = User(id=1, github_id=9, github_login="old", email=None)
    db = AsyncMock()
    db.add = MagicMock()
    db.execute = AsyncMock(side_effect=[scalar_result(None), scalar_result(created)])

    profile = GitHubUserProfile(id=9, login="octo", email=None)
    token = GitHubAccessTokenResponse(
        access_token="gho_new",
        token_type="bearer",
        scope="repo",
    )

    async def _inner():
        first = await upsert_github_user(db, profile, token, "a@example.com")
        second = await upsert_github_user(db, profile, token, None)
        return first, second

    first, second = asyncio.run(_inner())
    assert first is db.add.call_args.args[0]
    assert first.github_login == "octo"
    assert first.email == "a@example.com"
    assert first.github_access_token == "gho_new"
    assert second is created
    assert created.github_access_token == "gho_new"
    assert db.commit.await_count == 2


def test_openrouter_parses_fenced_json_aliases_and_line_ranges():
    raw = """```json
    {"summary":"ship it","findings":[{
      "severity":"blocker",
      "summary":"overflow",
      "file_path":" a.py ",
      "start_line":"12",
      "end_line":4,
      "suggestion":" clamp "
    },{
      "severity":"warning",
      "summary":"style",
      "file_path":null,
      "start_line":true,
      "end_line":null,
      "suggestion":""
    }]}
    ```"""
    provider = OpenRouterReviewProvider(AsyncMock(), "openrouter/free")
    result = provider._parse_review_response(raw)
    assert result.summary == "ship it"
    assert result.findings[0].severity == "critical"
    assert result.findings[0].file_path == "a.py"
    assert result.findings[0].start_line == 4
    assert result.findings[0].end_line == 12
    assert result.findings[0].suggestion == "clamp"
    assert result.findings[1].severity == "medium"
    assert result.findings[1].start_line is None
    assert result.findings[1].suggestion is None


def test_openrouter_review_content_rejects_empty_and_accepts_object_content():
    def handler(request: httpx.Request) -> httpx.Response:
        payload = json_body(request)
        if payload["messages"][1]["content"] == "empty":
            return httpx.Response(
                200,
                json={
                    "choices": [
                        {
                            "finish_reason": "stop",
                            "message": {"content": "   ", "role": "assistant"},
                        }
                    ]
                },
            )
        return httpx.Response(
            200,
            json={
                "choices": [
                    {
                        "message": {
                            "content": {
                                "summary": "ok",
                                "findings": [],
                            }
                        }
                    }
                ]
            },
        )

    async def _inner():
        async with _client(handler) as client:
            provider = OpenRouterReviewProvider(client, "openrouter/free")
            with pytest.raises(ValueError, match="empty content"):
                await provider.review_content("empty")
            parsed = await provider.review_content("full")
            return parsed, provider

    parsed, provider = asyncio.run(_inner())
    assert parsed.summary == "ok"
    assert parsed.findings == []
    assert provider.model_name == "openrouter/free"


def test_openrouter_rejects_missing_summary_and_non_list_findings():
    provider = OpenRouterReviewProvider(AsyncMock(), "openrouter/free")
    with pytest.raises(ValueError, match="missing summary"):
        provider._parse_review_response('{"summary":"","findings":[]}')
    with pytest.raises(TypeError, match="findings"):
        provider._parse_review_response('{"summary":"ok","findings":{}}')
    with pytest.raises(ValueError, match="summary"):
        provider._parse_finding({"severity": "high"})


def test_webhook_task_runs_the_pipeline():
    with patch(
        "app.tasks.github_webhooks.process_github_pull_request_event",
        new=AsyncMock(),
    ) as pipeline:
        result = process_github_pull_request_webhook.run(
            {"pull_request": {"url": "https://api.github.com/pulls/1"}}
        )
    assert result == {"ok": True}
    pipeline.assert_awaited_once()


def test_pipeline_skips_unknown_repo_missing_token_and_reuses_active_job():
    payload = {
        "repository": {"id": 11},
        "pull_request": {"number": 4, "id": 40, "url": "https://api.github.com/pulls/4"},
    }

    async def _unknown():
        db = AsyncMock()
        with (
            patch(
                "app.services.github_webhook_pipeline.AsyncSessionLocal",
                return_value=async_cm(db),
            ),
            patch(
                "app.services.github_webhook_pipeline.list_repo_by_github_repo_id",
                new=AsyncMock(return_value=[]),
            ),
            patch(
                "app.services.github_webhook_pipeline.sync_pull_requests",
                new=AsyncMock(),
            ) as sync,
        ):
            await process_github_pull_request_event(payload)
        sync.assert_not_awaited()

    asyncio.run(_unknown())

    repo = SimpleNamespace(
        id=3,
        user=SimpleNamespace(id=7, github_access_token=None),
        owner_login="octo",
        name="demo",
    )

    async def _no_token():
        with (
            patch(
                "app.services.github_webhook_pipeline.AsyncSessionLocal",
                return_value=async_cm(AsyncMock()),
            ),
            patch(
                "app.services.github_webhook_pipeline.list_repo_by_github_repo_id",
                new=AsyncMock(return_value=[repo]),
            ),
            patch(
                "app.services.github_webhook_pipeline.sync_pull_requests",
                new=AsyncMock(return_value=[SimpleNamespace(id=8, number=4)]),
            ) as sync,
            patch(
                "app.services.github_webhook_pipeline.call_with_github_token",
                new=AsyncMock(side_effect=GitHubTokenUnavailable("reconnect")),
            ),
            patch(
                "app.services.github_webhook_pipeline.create_review_job_if_no_active",
                new=AsyncMock(),
            ) as create_job,
            patch(
                "app.services.github_webhook_pipeline.execute_review_job_task.delay"
            ) as delay,
        ):
            await process_github_pull_request_event(payload)
        sync.assert_awaited()
        create_job.assert_not_awaited()
        delay.assert_not_called()

    asyncio.run(_no_token())

    owner_repo = SimpleNamespace(
        id=3,
        user=SimpleNamespace(id=7, github_access_token="gho"),
        owner_login="octo",
        name="demo",
    )
    pull_request = SimpleNamespace(id=8, number=4)
    active = ReviewJob(
        id=21,
        pull_request_id=8,
        status=ReviewJobStatus.pending,
        provider="openrouter",
        model_name="openrouter/free",
    )

    async def _reuse():
        with (
            patch(
                "app.services.github_webhook_pipeline.AsyncSessionLocal",
                return_value=async_cm(AsyncMock()),
            ),
            patch(
                "app.services.github_webhook_pipeline.list_repo_by_github_repo_id",
                new=AsyncMock(return_value=[owner_repo]),
            ),
            patch(
                "app.services.github_webhook_pipeline.sync_pull_requests",
                new=AsyncMock(return_value=[pull_request]),
            ) as sync,
            patch(
                "app.services.github_webhook_pipeline.call_with_github_token",
                new=_pass_github_token,
            ),
            patch(
                "app.services.github_webhook_pipeline.fetch_github_pull_request_files",
                new=AsyncMock(return_value=[{"filename": "a.py"}]),
            ),
            patch(
                "app.services.github_webhook_pipeline.sync_pull_request_files",
                new=AsyncMock(return_value=[]),
            ),
            patch(
                "app.services.github_webhook_pipeline.create_review_job_if_no_active",
                new=AsyncMock(return_value=(active, False)),
            ) as create_job,
            patch(
                "app.services.github_webhook_pipeline.execute_review_job_task.delay"
            ) as delay,
        ):
            await process_github_pull_request_event(payload)
        assert sync.await_args.kwargs.get("replace_missing", False) is False
        assert create_job.await_args.kwargs["model_name"]
        delay.assert_not_called()

    asyncio.run(_reuse())


def test_pipeline_creates_and_enqueues_a_job_per_local_repo():
    payload = {
        "repository": {"id": 11},
        "pull_request": {"number": 4, "id": 40},
    }
    repos = [
        SimpleNamespace(
            id=1,
            user=SimpleNamespace(id=7, github_access_token="gho"),
            owner_login="octo",
            name="demo",
        ),
        SimpleNamespace(
            id=2,
            user=None,
            owner_login="octo",
            name="demo",
        ),
    ]
    pull_request = SimpleNamespace(id=8, number=4)
    job = ReviewJob(
        id=30,
        pull_request_id=8,
        status=ReviewJobStatus.pending,
        provider="openrouter",
        model_name="openrouter/free",
    )

    async def _inner():
        with (
            patch(
                "app.services.github_webhook_pipeline.AsyncSessionLocal",
                return_value=async_cm(AsyncMock()),
            ),
            patch(
                "app.services.github_webhook_pipeline.list_repo_by_github_repo_id",
                new=AsyncMock(return_value=repos),
            ),
            patch(
                "app.services.github_webhook_pipeline.sync_pull_requests",
                new=AsyncMock(return_value=[pull_request]),
            ) as sync,
            patch(
                "app.services.github_webhook_pipeline.call_with_github_token",
                new=_pass_github_token,
            ),
            patch(
                "app.services.github_webhook_pipeline.fetch_github_pull_request_files",
                new=AsyncMock(return_value=[]),
            ),
            patch(
                "app.services.github_webhook_pipeline.sync_pull_request_files",
                new=AsyncMock(),
            ),
            patch(
                "app.services.github_webhook_pipeline.create_review_job_if_no_active",
                new=AsyncMock(return_value=(job, True)),
            ),
            patch(
                "app.services.github_webhook_pipeline.execute_review_job_task.delay"
            ) as delay,
        ):
            await process_github_pull_request_event(payload)
        return sync, delay

    sync, delay = asyncio.run(_inner())
    sync.assert_awaited_once()
    delay.assert_called_once_with(30)


def test_pipeline_enqueue_failure_marks_the_job_failed():
    payload = {
        "repository": {"id": 11},
        "pull_request": {"number": 4},
    }
    repo = SimpleNamespace(
        id=1,
        user=SimpleNamespace(id=7, github_access_token="gho"),
        owner_login="octo",
        name="demo",
    )
    db = AsyncMock()
    job = ReviewJob(
        id=30,
        pull_request_id=8,
        status=ReviewJobStatus.pending,
        provider="openrouter",
        model_name="openrouter/free",
    )

    async def _inner():
        with (
            patch(
                "app.services.github_webhook_pipeline.AsyncSessionLocal",
                return_value=async_cm(db),
            ),
            patch(
                "app.services.github_webhook_pipeline.list_repo_by_github_repo_id",
                new=AsyncMock(return_value=[repo]),
            ),
            patch(
                "app.services.github_webhook_pipeline.sync_pull_requests",
                new=AsyncMock(return_value=[SimpleNamespace(id=8, number=4)]),
            ),
            patch(
                "app.services.github_webhook_pipeline.call_with_github_token",
                new=_pass_github_token,
            ),
            patch(
                "app.services.github_webhook_pipeline.fetch_github_pull_request_files",
                new=AsyncMock(return_value=[]),
            ),
            patch(
                "app.services.github_webhook_pipeline.sync_pull_request_files",
                new=AsyncMock(),
            ),
            patch(
                "app.services.github_webhook_pipeline.create_review_job_if_no_active",
                new=AsyncMock(return_value=(job, True)),
            ),
            patch(
                "app.services.github_webhook_pipeline.execute_review_job_task.delay",
                side_effect=RuntimeError("broker"),
            ),
        ):
            await process_github_pull_request_event(payload)

    with pytest.raises(RuntimeError):
        asyncio.run(_inner())
    assert job.status == ReviewJobStatus.failed
    assert "Failed to enqueue" in (job.error_message or "")
    db.commit.assert_awaited()


def test_pipeline_ignores_payloads_without_a_pull_request_number():
    async def _inner():
        with patch(
            "app.services.github_webhook_pipeline.AsyncSessionLocal",
            side_effect=AssertionError("db should not open"),
        ):
            await process_github_pull_request_event(
                {"repository": {"id": 1}, "pull_request": {}}
            )

    asyncio.run(_inner())


def json_body(request: httpx.Request) -> dict:
    import json

    return json.loads(request.content.decode())
