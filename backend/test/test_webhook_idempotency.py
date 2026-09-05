import asyncio
import hashlib
import hmac
import json
from unittest.mock import AsyncMock, MagicMock, patch

from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import get_db
from app.api.webhooks import router, settings
from app.services.github_webhook_events import register_github_webhook_event


def _signed_headers(
    body: bytes,
    *,
    event: str,
    delivery_id: str | None = "delivery-123",
) -> dict[str, str]:
    signature = "sha256=" + hmac.new(
        settings.github_webhook_secret.encode("utf-8"),
        body,
        hashlib.sha256,
    ).hexdigest()
    headers = {
        "Content-Type": "application/json",
        "X-Hub-Signature-256": signature,
        "X-GitHub-Event": event,
    }
    if delivery_id is not None:
        headers["X-GitHub-Delivery"] = delivery_id
    return headers


def _pull_request_body() -> bytes:
    return json.dumps(
        {
            "action": "synchronize",
            "repository": {
                "id": 123,
                "full_name": "octocat/repo-guard",
            },
            "pull_request": {
                "number": 7,
            },
        }
    ).encode("utf-8")


def _test_client() -> TestClient:
    app = FastAPI()
    app.include_router(router)
    db = AsyncMock(spec=AsyncSession)

    async def override_get_db():
        yield db

    app.dependency_overrides[get_db] = override_get_db
    return TestClient(app)


def test_delivery_registration_returns_whether_insert_succeeded():
    inserted_result = MagicMock()
    inserted_result.scalar_one_or_none.return_value = 42
    duplicate_result = MagicMock()
    duplicate_result.scalar_one_or_none.return_value = None
    db = AsyncMock(spec=AsyncSession)
    db.execute.side_effect = [inserted_result, duplicate_result]

    first_inserted = asyncio.run(
        register_github_webhook_event(
            db,
            delivery_id="delivery-123",
            event_name="pull_request",
            action="synchronize",
            github_repo_id=123,
            pull_request_number=7,
        )
    )
    duplicate_inserted = asyncio.run(
        register_github_webhook_event(
            db,
            delivery_id="delivery-123",
            event_name="pull_request",
            action="synchronize",
            github_repo_id=123,
            pull_request_number=7,
        )
    )

    assert first_inserted is True
    assert duplicate_inserted is False
    assert db.commit.await_count == 2


def test_new_delivery_is_registered_and_dispatched():
    body = _pull_request_body()

    with (
        patch(
            "app.api.webhooks.register_github_webhook_event",
            new=AsyncMock(return_value=True),
        ) as register,
        patch(
            "app.api.webhooks.process_github_pull_request_webhook.delay"
        ) as dispatch,
    ):
        response = _test_client().post(
            "/webhooks/github",
            content=body,
            headers=_signed_headers(body, event="pull_request"),
        )

    assert response.status_code == 200
    assert response.json()["duplicate"] is False
    assert response.json()["dispatched"] is True
    register.assert_awaited_once()
    dispatch.assert_called_once()


def test_duplicate_delivery_returns_200_without_dispatching():
    body = _pull_request_body()

    with (
        patch(
            "app.api.webhooks.register_github_webhook_event",
            new=AsyncMock(return_value=False),
        ),
        patch(
            "app.api.webhooks.process_github_pull_request_webhook.delay"
        ) as dispatch,
    ):
        response = _test_client().post(
            "/webhooks/github",
            content=body,
            headers=_signed_headers(body, event="pull_request"),
        )

    assert response.status_code == 200
    assert response.json()["duplicate"] is True
    assert response.json()["dispatched"] is False
    dispatch.assert_not_called()


def test_publish_failure_removes_delivery_and_returns_503():
    body = _pull_request_body()

    with (
        patch(
            "app.api.webhooks.register_github_webhook_event",
            new=AsyncMock(return_value=True),
        ),
        patch(
            "app.api.webhooks.delete_github_webhook_event",
            new=AsyncMock(),
        ) as delete_event,
        patch(
            "app.api.webhooks.process_github_pull_request_webhook.delay",
            new=MagicMock(side_effect=RuntimeError("broker unavailable")),
        ),
    ):
        response = _test_client().post(
            "/webhooks/github",
            content=body,
            headers=_signed_headers(body, event="pull_request"),
        )

    assert response.status_code == 503
    delete_event.assert_awaited_once()


def test_ping_returns_200_without_registration_or_dispatch():
    body = json.dumps({"zen": "Keep it logically awesome."}).encode("utf-8")

    with (
        patch(
            "app.api.webhooks.register_github_webhook_event",
            new=AsyncMock(),
        ) as register,
        patch(
            "app.api.webhooks.process_github_pull_request_webhook.delay"
        ) as dispatch,
    ):
        response = _test_client().post(
            "/webhooks/github",
            content=body,
            headers=_signed_headers(body, event="ping"),
        )

    assert response.status_code == 200
    assert response.json()["handled"] is False
    register.assert_not_awaited()
    dispatch.assert_not_called()
