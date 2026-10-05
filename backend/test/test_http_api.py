import hashlib
import hmac
import json
from datetime import datetime, timedelta, timezone
from unittest.mock import AsyncMock, MagicMock, patch

import jwt  # pyright: ignore[reportMissingImports]
import pytest  # pyright: ignore[reportMissingImports]
from app.api.auth import router as auth_router
from app.api.deps import get_current_user, get_db
from app.api.pr_files import router as files_router
from app.api.pull_requests import router as pull_requests_router
from app.api.repositories import router as repositories_router
from app.api.review_jobs import router as review_jobs_router
from app.api.webhooks import router as webhooks_router
from app.api.webhooks import settings as webhook_settings
from app.core.config import get_settings
from app.core.security import create_access_token, decode_access_token
from app.models.review_job import ReviewJob, ReviewJobStatus
from app.models.user import User
from app.schemas.auth import GitHubAccessTokenResponse, GitHubUserProfile
from app.services.github_tokens import GitHubTokenUnavailable
from fastapi import FastAPI  # pyright: ignore[reportMissingImports]
from fastapi.testclient import TestClient  # pyright: ignore[reportMissingImports]
from helpers import scalar_result

settings = get_settings()


async def _pass_github_token(_user_id, _http_client, operation):
    return await operation("gho_test")


def _user(**overrides) -> User:
    values = {
        "id": 7,
        "github_id": 70,
        "github_login": "octo",
        "email": "octo@example.com",
        "github_access_token": "gho_test",
    }
    values.update(overrides)
    return User(**values)


def _client(*routers, user: User | None = None, db: AsyncMock | None = None) -> TestClient:
    app = FastAPI()
    for router in routers:
        app.include_router(router)
    database = db or AsyncMock()

    async def override_db():
        yield database

    app.dependency_overrides[get_db] = override_db
    if user is not None:
        app.dependency_overrides[get_current_user] = lambda: user
    app.state.http_client = AsyncMock()
    return TestClient(app)


def _signed(body: bytes, *, event: str, delivery: str | None = "delivery-1", secret: str | None = None) -> dict:
    key = (secret if secret is not None else webhook_settings.github_webhook_secret).encode()
    headers = {
        "Content-Type": "application/json",
        "X-Hub-Signature-256": "sha256=" + hmac.new(key, body, hashlib.sha256).hexdigest(),
        "X-GitHub-Event": event,
    }
    if delivery is not None:
        headers["X-GitHub-Delivery"] = delivery
    return headers


def _pull_body(action: str = "opened") -> bytes:
    return json.dumps(
        {
            "action": action,
            "repository": {"id": 11, "full_name": "octo/demo"},
            "pull_request": {"number": 4},
        }
    ).encode()


def test_access_token_roundtrip_and_rejection():
    token = create_access_token(7)
    payload = decode_access_token(token)
    assert payload["sub"] == "7"

    expired = jwt.encode(
        {"sub": "7", "exp": datetime.now(timezone.utc) - timedelta(minutes=1)},
        settings.jwt_secret_key,
        algorithm=settings.jwt_algorithm,
    )
    with pytest.raises(Exception) as exc_info:
        decode_access_token(expired)
    assert exc_info.value.status_code == 401

    with pytest.raises(Exception) as bad:
        decode_access_token("not-a-jwt")
    assert bad.value.status_code == 401


def test_me_accepts_bearer_and_cookie_and_rejects_missing_user():
    user = _user()
    db = AsyncMock()
    db.execute = AsyncMock(return_value=scalar_result(user))
    client = _client(auth_router, db=db)
    token = create_access_token(user.id)

    bearer = client.get("/auth/me", headers={"Authorization": f"Bearer {token}"})
    assert bearer.status_code == 200
    assert bearer.json()["github_login"] == "octo"

    cookie = client.get(
        "/auth/me",
        cookies={settings.access_token_cookie_name: token},
    )
    assert cookie.status_code == 200

    anonymous = client.get("/auth/me")
    assert anonymous.status_code == 401

    db.execute = AsyncMock(return_value=scalar_result(None))
    missing = client.get("/auth/me", headers={"Authorization": f"Bearer {token}"})
    assert missing.status_code == 401
    assert missing.json()["detail"] == "User not found"


def test_token_without_sub_is_unauthorized_and_non_numeric_sub_is_unhandled():
    from app.api.deps import get_current_user as resolve_user

    no_sub = jwt.encode(
        {"exp": datetime.now(timezone.utc) + timedelta(minutes=5)},
        settings.jwt_secret_key,
        algorithm=settings.jwt_algorithm,
    )
    bad_sub = jwt.encode(
        {"sub": "octo", "exp": datetime.now(timezone.utc) + timedelta(minutes=5)},
        settings.jwt_secret_key,
        algorithm=settings.jwt_algorithm,
    )
    request = MagicMock()
    request.cookies = {}

    with pytest.raises(Exception) as exc_info:
        asyncio_run(resolve_user(request, no_sub, AsyncMock()))
    assert exc_info.value.status_code == 401

    with pytest.raises(ValueError):
        asyncio_run(resolve_user(request, bad_sub, AsyncMock()))


def test_github_login_sets_state_cookie_and_callback_rejects_mismatch():
    client = _client(auth_router)
    response = client.get("/auth/github/login", follow_redirects=False)
    assert response.status_code == 302
    assert response.headers["location"].startswith(
        "https://github.com/login/oauth/authorize?"
    )
    assert settings.oauth_state_cookie_name in response.cookies

    rejected = client.get(
        "/auth/github/callback",
        params={"code": "abc", "state": "nope"},
        follow_redirects=False,
    )
    assert rejected.status_code == 400
    assert rejected.json()["detail"] == "Invalid OAuth state"


def test_github_callback_sets_session_cookie_and_logout_clears_it():
    user = _user()
    client = _client(auth_router)
    state = "state-token"
    client.cookies.set(settings.oauth_state_cookie_name, state)

    with (
        patch(
            "app.api.auth.exchange_code_for_access_token",
            new=AsyncMock(
                return_value=GitHubAccessTokenResponse(
                    access_token="gho_new",
                    token_type="bearer",
                    scope="repo",
                )
            ),
        ),
        patch(
            "app.api.auth.fetch_github_user",
            new=AsyncMock(
                return_value=GitHubUserProfile(id=70, login="octo", email=None)
            ),
        ),
        patch("app.api.auth.fetch_primary_email", new=AsyncMock(return_value="octo@example.com")),
        patch("app.api.auth.upsert_github_user", new=AsyncMock(return_value=user)),
    ):
        response = client.get(
            "/auth/github/callback",
            params={"code": "abc", "state": state},
            follow_redirects=False,
        )

    assert response.status_code == 302
    assert response.headers["location"] == settings.frontend_url
    assert settings.access_token_cookie_name in response.cookies
    set_cookie = response.headers.get("set-cookie", "")
    assert f'{settings.oauth_state_cookie_name}=""' in set_cookie or "Max-Age=0" in set_cookie

    logout = client.post("/auth/logout")
    assert logout.status_code == 204
    cleared = logout.headers.get("set-cookie", "")
    assert settings.access_token_cookie_name in cleared


def test_repository_sync_requires_token_and_returns_synced_items():
    client = _client(repositories_router, user=_user())
    with patch(
        "app.api.repositories.call_with_github_token",
        new=AsyncMock(side_effect=GitHubTokenUnavailable("reconnect")),
    ):
        missing = client.post("/repositories/sync")
    assert missing.status_code == 401

    owner = _user()
    client = _client(repositories_router, user=owner)
    repo = MagicMock()
    repo.id = 1
    repo.github_repo_id = 11
    repo.name = "demo"
    repo.full_name = "octo/demo"
    repo.owner_login = "octo"
    repo.private = False
    repo.default_branch = "main"
    repo.updated_at = datetime(2026, 1, 2, tzinfo=timezone.utc)

    with (
        patch(
            "app.api.repositories.call_with_github_token",
            new=_pass_github_token,
        ),
        patch("app.api.repositories.fetch_github_repositories", new=AsyncMock(return_value=[])),
        patch("app.api.repositories.sync_repositories", new=AsyncMock(return_value=[repo])),
    ):
        response = client.post("/repositories/sync")

    assert response.status_code == 200
    body = response.json()
    assert body["count"] == 1
    assert body["items"][0]["full_name"] == "octo/demo"


def test_pull_request_sync_404_for_foreign_repo_and_lists_stored_prs():
    user = _user()
    client = _client(pull_requests_router, user=user)

    with patch("app.api.pull_requests.get_repo_for_user", new=AsyncMock(return_value=None)):
        missing = client.post("/repositories/9/pr/sync")
        listing = client.get("/repositories/9/pull-requests")
    assert missing.status_code == 404
    assert listing.status_code == 404

    repo = MagicMock(owner_login="octo", name="demo")
    pr = MagicMock()
    pr.id = 3
    pr.github_pr_id = 30
    pr.number = 8
    pr.title = "Add tests"
    pr.state = "open"
    pr.author_login = "octo"
    pr.html_url = "https://github.com/octo/demo/pull/8"
    pr.base_branch = "main"
    pr.head_branch = "tests"
    pr.is_draft = False
    pr.github_created_at = datetime(2026, 1, 1, tzinfo=timezone.utc)
    pr.github_updated_at = datetime(2026, 1, 2, tzinfo=timezone.utc)
    pr.github_closed_at = None
    pr.github_merged_at = None

    with (
        patch("app.api.pull_requests.get_repo_for_user", new=AsyncMock(return_value=repo)),
        patch(
            "app.api.pull_requests.call_with_github_token",
            new=_pass_github_token,
        ),
        patch(
            "app.api.pull_requests.fetch_github_pull_requests",
            new=AsyncMock(return_value=[{"id": 30}]),
        ) as fetch,
        patch(
            "app.api.pull_requests.sync_pull_requests",
            new=AsyncMock(return_value=[pr]),
        ) as sync,
    ):
        response = client.post("/repositories/9/pr/sync")

    assert response.status_code == 200
    assert response.json()["items"][0]["number"] == 8
    fetch.assert_awaited()
    assert sync.await_args.kwargs["replace_missing"] is True


def test_file_sync_requires_token_and_get_file_hides_other_users():
    client = _client(files_router, user=_user())
    with (
        patch(
            "app.api.pr_files.get_pull_request_with_repository",
            new=AsyncMock(return_value=(MagicMock(number=4), MagicMock())),
        ),
        patch(
            "app.api.pr_files.call_with_github_token",
            new=AsyncMock(side_effect=GitHubTokenUnavailable("reconnect")),
        ),
    ):
        assert client.post("/pull-requests/4/files/sync").status_code == 401

    owner = _user()
    client = _client(files_router, user=owner)
    with patch(
        "app.api.pr_files.get_pull_request_with_repository",
        new=AsyncMock(return_value=(None, None)),
    ):
        assert client.get("/pull-requests/4").status_code == 404
        assert client.get("/pull-requests/4/files").status_code == 404

    with patch("app.api.pr_files.get_PR_file_for_user", new=AsyncMock(return_value=None)):
        hidden = client.get("/pull-requests/4/files/9")
    assert hidden.status_code == 404
    assert hidden.json()["detail"] == "Pull request file not found"


def test_review_job_create_enqueues_once_and_reuses_active_job():
    user = _user()
    client = _client(review_jobs_router, user=user)
    pull_request = MagicMock(id=4)
    created = _review_job(15, ReviewJobStatus.pending)
    existing = _review_job(15, ReviewJobStatus.processing)

    with (
        patch(
            "app.api.review_jobs.get_pull_request_for_user",
            new=AsyncMock(return_value=pull_request),
        ),
        patch(
            "app.api.review_jobs.create_review_job_if_no_active",
            new=AsyncMock(return_value=(created, True)),
        ),
        patch("app.api.review_jobs.execute_review_job_task.delay") as delay,
        patch(
            "app.api.review_jobs.get_review_job_with_findings_for_user",
            new=AsyncMock(return_value=created),
        ),
    ):
        response = client.post(
            "/pull-requests/4/review-jobs",
            json={"provider": "openrouter", "model_name": "openrouter/free"},
        )

    assert response.status_code == 202
    assert response.json()["status"] == "pending"
    assert response.json()["total_chunks"] == 0
    delay.assert_called_once_with(15)

    with (
        patch(
            "app.api.review_jobs.get_pull_request_for_user",
            new=AsyncMock(return_value=pull_request),
        ),
        patch(
            "app.api.review_jobs.create_review_job_if_no_active",
            new=AsyncMock(return_value=(existing, False)),
        ),
        patch("app.api.review_jobs.execute_review_job_task.delay") as delay_again,
        patch(
            "app.api.review_jobs.get_review_job_with_findings_for_user",
            new=AsyncMock(return_value=existing),
        ),
    ):
        reused = client.post(
            "/pull-requests/4/review-jobs",
            json={"model_name": "nvidia/nemotron-3-ultra-550b-a55b:free"},
        )

    assert reused.status_code == 202
    assert reused.json()["status"] == "processing"
    delay_again.assert_not_called()


def test_review_job_enqueue_failure_marks_failed_and_returns_503():
    user = _user()
    db = AsyncMock()
    client = _client(review_jobs_router, user=user, db=db)
    job = _review_job(15, ReviewJobStatus.pending)

    with (
        patch(
            "app.api.review_jobs.get_pull_request_for_user",
            new=AsyncMock(return_value=MagicMock(id=4)),
        ),
        patch(
            "app.api.review_jobs.create_review_job_if_no_active",
            new=AsyncMock(return_value=(job, True)),
        ),
        patch(
            "app.api.review_jobs.execute_review_job_task.delay",
            side_effect=RuntimeError("broker down"),
        ),
    ):
        response = client.post(
            "/pull-requests/4/review-jobs",
            json={"model_name": "openrouter/free"},
        )

    assert response.status_code == 503
    assert job.status == ReviewJobStatus.failed
    assert "Failed to enqueue" in (job.error_message or "")
    db.commit.assert_awaited()


def test_review_reads_are_404_when_the_user_does_not_own_them():
    user = _user()
    client = _client(review_jobs_router, user=user)

    with patch(
        "app.api.review_jobs.get_pull_request_for_user",
        new=AsyncMock(return_value=None),
    ):
        created = client.post(
            "/pull-requests/4/review-jobs",
            json={"model_name": "openrouter/free"},
        )
        listed = client.get("/pull-requests/4/review-jobs")
    assert created.status_code == 404
    assert listed.status_code == 404

    with patch(
        "app.api.review_jobs.get_review_job_with_findings_for_user",
        new=AsyncMock(return_value=None),
    ):
        hidden = client.get("/review-jobs/99")
    assert hidden.status_code == 404

    unknown = client.post(
        "/pull-requests/4/review-jobs",
        json={"model_name": "openai/gpt-4o"},
    )
    assert unknown.status_code == 422


def test_review_model_list_uses_the_allowlist():
    client = _client(review_jobs_router, user=_user())
    response = client.get("/review-models")
    assert response.status_code == 200
    body = response.json()
    assert "openrouter/free" in body["models"]
    assert "nvidia/nemotron-3-ultra-550b-a55b:free" in body["models"]
    assert body["default_model"] in body["models"]


def test_webhook_rejects_bad_signature_invalid_json_and_missing_delivery():
    client = _client(webhooks_router)
    body = _pull_body()
    bad = client.post(
        "/webhooks/github",
        content=body,
        headers={
            "X-Hub-Signature-256": "sha256=" + "0" * 64,
            "X-GitHub-Event": "pull_request",
            "X-GitHub-Delivery": "d1",
        },
    )
    assert bad.status_code == 401

    signed_garbage = b"{"
    invalid = client.post(
        "/webhooks/github",
        content=signed_garbage,
        headers=_signed(signed_garbage, event="pull_request"),
    )
    assert invalid.status_code == 400

    missing_delivery = client.post(
        "/webhooks/github",
        content=body,
        headers=_signed(body, event="pull_request", delivery=None),
    )
    assert missing_delivery.status_code == 400
    assert "X-GitHub-Delivery" in missing_delivery.json()["detail"]


def test_webhook_ignores_closed_and_dispatches_opened():
    client = _client(webhooks_router)
    closed = _pull_body("closed")
    with (
        patch("app.api.webhooks.register_github_webhook_event", new=AsyncMock()) as register,
        patch("app.api.webhooks.process_github_pull_request_webhook.delay") as delay,
    ):
        response = client.post(
            "/webhooks/github",
            content=closed,
            headers=_signed(closed, event="pull_request"),
        )
    assert response.status_code == 200
    assert response.json()["handled"] is False
    register.assert_not_awaited()
    delay.assert_not_called()

    opened = _pull_body("opened")
    with (
        patch(
            "app.api.webhooks.register_github_webhook_event",
            new=AsyncMock(return_value=True),
        ),
        patch("app.api.webhooks.process_github_pull_request_webhook.delay") as delay,
    ):
        response = client.post(
            "/webhooks/github",
            content=opened,
            headers=_signed(opened, event="pull_request", delivery="delivery-opened"),
        )
    assert response.status_code == 200
    assert response.json()["dispatched"] is True
    assert response.json()["action"] == "opened"
    delay.assert_called_once()


def _review_job(job_id: int, status: ReviewJobStatus) -> ReviewJob:
    job = ReviewJob(
        id=job_id,
        pull_request_id=4,
        status=status,
        provider="openrouter",
        model_name="openrouter/free",
        total_files=1,
        total_chunks=0,
    )
    job.created_at = datetime(2026, 1, 1, tzinfo=timezone.utc)
    job.updated_at = datetime(2026, 1, 1, tzinfo=timezone.utc)
    job.findings = []
    return job


def asyncio_run(coro):
    import asyncio

    return asyncio.run(coro)
