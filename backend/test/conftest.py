import os

# Deterministic settings before app modules cache `get_settings()`.
os.environ.setdefault("ENVIRONMENT", "test")
os.environ.setdefault("NEON_POSTGRES_URL", "postgresql://user:pass@localhost/ci")
os.environ.setdefault("UPSTASH_REDIS_REST_URL", "https://example.com")
os.environ.setdefault("UPSTASH_REDIS_REST_TOKEN", "ci")
os.environ.setdefault("GITHUB_CLIENT_ID", "ci")
os.environ.setdefault("GITHUB_CLIENT_SECRET", "ci")
os.environ.setdefault(
    "GITHUB_REDIRECT_URI", "http://localhost:8000/auth/github/callback"
)
os.environ.setdefault(
    "GITHUB_WEBHOOK_SECRET", "ci-webhook-secret-at-least-32-chars"
)
os.environ.setdefault("FRONTEND_URL", "http://localhost:3000")
os.environ.setdefault("GITHUB_OAUTH_SCOPE", "read:user user:email repo")
os.environ.setdefault("OAUTH_STATE_COOKIE_NAME", "codeguard_oauth_state")
os.environ.setdefault("COOKIE_SECURE", "false")
os.environ.setdefault("JWT_SECRET_KEY", "ci-jwt-secret-key-at-least-32-chars")
os.environ.setdefault("JWT_ALGORITHM", "HS256")
os.environ.setdefault("ACCESS_TOKEN_EXPIRE_MINUTES", "60")
os.environ.setdefault("OPEN_ROUTER_API_KEY", "ci")
os.environ.setdefault("RATE_LIMIT_ENABLED", "false")

import pytest  # pyright: ignore[reportMissingImports]

from app.core.celery_app import celery_app


@pytest.fixture(autouse=True)
def celery_eager_mode():
    """Run tasks in-process so tests do not need RabbitMQ."""
    celery_app.conf.task_always_eager = True
    celery_app.conf.task_eager_propagates = True
    yield
    celery_app.conf.task_always_eager = False
    celery_app.conf.task_eager_propagates = False