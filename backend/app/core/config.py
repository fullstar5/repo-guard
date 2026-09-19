from functools import lru_cache
from pathlib import Path
from typing import Literal
from urllib.parse import urlsplit

from pydantic import model_validator  # pyright: ignore[reportMissingImports]
from pydantic_settings import BaseSettings, SettingsConfigDict  # pyright: ignore[reportMissingImports]

BASE_DIR = Path(__file__).resolve().parents[2]


class Settings(BaseSettings):
    environment: Literal["development", "test", "production"] = "development"

    neon_postgres_url: str
    upstash_redis_rest_url: str
    upstash_redis_rest_token: str

    github_client_id: str
    github_client_secret: str
    github_redirect_uri: str
    github_webhook_secret: str   # used to authenticate message from github

    frontend_url: str
    github_oauth_scope: str
    oauth_state_cookie_name: str
    cookie_secure: bool
    access_token_cookie_name: str = "codeguard_access_token"

    jwt_secret_key: str
    jwt_algorithm: str
    access_token_expire_minutes: int

    open_router_api_key: str
    open_router_base_url: str = "https://openrouter.ai/api/v1"
    open_router_default_model: str = "openrouter/free"
    app_public_url: str = "http://localhost:3000"
    app_name: str = "CodeGuard AI"

    # OpenRouter timeouts:
    openrouter_connect_timeout: float = 10.0
    # Larger than the 1h Celery soft limit so wait_for/httpx never
    # beat SoftTimeLimitExceeded and mark the job failed first.
    openrouter_read_timeout: float = 7200.0

    # Original combined/chunk limits. Unused after GitHub window packing.
    # review_max_combined_chars: int = 120000
    # review_max_patch_chars: int = 20000
    # review_max_combined_files: int = 30
    # review_max_combined_changes: int = 1000
    review_retry_attempts: int = 3
    review_pack_max_chars: int = 8000
    review_context_lines: int = 40

    # Upstash-backed distributed rate limiting. Local development may disable
    # it, but production validation requires fail-closed protection.
    rate_limit_enabled: bool = False
    rate_limit_timeout_seconds: float = 1.5
    rate_limit_trusted_proxy_hops: int = 1
    rate_limit_oauth_requests: int = 20
    rate_limit_oauth_window_seconds: int = 600
    rate_limit_sync_user_requests: int = 30
    rate_limit_sync_user_window_seconds: int = 600
    rate_limit_sync_object_requests: int = 6
    rate_limit_sync_object_window_seconds: int = 60
    rate_limit_review_user_requests: int = 5
    rate_limit_review_user_window_seconds: int = 3600
    rate_limit_review_object_requests: int = 2
    rate_limit_review_object_window_seconds: int = 600


    # RabbitMQ and celery
    rabbitmq_url: str = "amqp://guest:guest@localhost:5672//"
    celery_result_backend: str = "rpc://"

    celery_task_max_retries: int = 3
    celery_task_retry_backoff_seconds: int = 5   # wait for x second before next try
    celery_task_retry_backoff_max: int = 300   #
    celery_task_soft_time_limit: int = 3600   # 1h wall clock; retry the whole job once
    celery_task_time_limit: int = 4200   # above soft so retry can enqueue and persist

    celery_task_reclaim_interval_seconds: float = 21600   # scan stale jobs every 6 hours
    review_job_stale_processing_seconds: int = 10800   # > 2h so a 1h run + 1 retry is not reclaimed


    model_config = SettingsConfigDict(
        env_file=BASE_DIR / ".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )

    @model_validator(mode="after")
    def validate_production_settings(self) -> "Settings":
        """
        Reject unsafe production configuration before the process starts.

        Local development keeps HTTP and localhost defaults. Production must
        use secure public URLs, secure cookies, and non-development secrets.
        """
        errors: list[str] = []
        positive_rate_limit_settings = {
            "RATE_LIMIT_TIMEOUT_SECONDS": self.rate_limit_timeout_seconds,
            "RATE_LIMIT_OAUTH_REQUESTS": self.rate_limit_oauth_requests,
            "RATE_LIMIT_OAUTH_WINDOW_SECONDS": self.rate_limit_oauth_window_seconds,
            "RATE_LIMIT_SYNC_USER_REQUESTS": self.rate_limit_sync_user_requests,
            "RATE_LIMIT_SYNC_USER_WINDOW_SECONDS": self.rate_limit_sync_user_window_seconds,
            "RATE_LIMIT_SYNC_OBJECT_REQUESTS": self.rate_limit_sync_object_requests,
            "RATE_LIMIT_SYNC_OBJECT_WINDOW_SECONDS": self.rate_limit_sync_object_window_seconds,
            "RATE_LIMIT_REVIEW_USER_REQUESTS": self.rate_limit_review_user_requests,
            "RATE_LIMIT_REVIEW_USER_WINDOW_SECONDS": self.rate_limit_review_user_window_seconds,
            "RATE_LIMIT_REVIEW_OBJECT_REQUESTS": self.rate_limit_review_object_requests,
            "RATE_LIMIT_REVIEW_OBJECT_WINDOW_SECONDS": self.rate_limit_review_object_window_seconds,
        }
        for name, value in positive_rate_limit_settings.items():
            if value <= 0:
                errors.append(f"{name} must be greater than zero")

        if self.rate_limit_trusted_proxy_hops < 0:
            errors.append("RATE_LIMIT_TRUSTED_PROXY_HOPS cannot be negative")

        if self.environment != "production":
            if errors:
                raise ValueError("; ".join(errors))
            return self

        if not self.rate_limit_enabled:
            errors.append("RATE_LIMIT_ENABLED must be true in production")

        secure_urls = {
            "FRONTEND_URL": self.frontend_url,
            "GITHUB_REDIRECT_URI": self.github_redirect_uri,
            "APP_PUBLIC_URL": self.app_public_url,
            "UPSTASH_REDIS_REST_URL": self.upstash_redis_rest_url,
            "OPEN_ROUTER_BASE_URL": self.open_router_base_url,
        }

        for name, value in secure_urls.items():
            if urlsplit(value).scheme != "https":
                errors.append(f"{name} must use https in production")

        if not self.cookie_secure:
            errors.append("COOKIE_SECURE must be true in production")

        if len(self.jwt_secret_key) < 32:
            errors.append("JWT_SECRET_KEY must contain at least 32 characters")

        if len(self.github_webhook_secret) < 32:
            errors.append(
                "GITHUB_WEBHOOK_SECRET must contain at least 32 characters"
            )

        database_host = urlsplit(self.neon_postgres_url).hostname
        if database_host in {"localhost", "127.0.0.1"}:
            errors.append("NEON_POSTGRES_URL cannot use localhost in production")

        rabbitmq_host = urlsplit(self.rabbitmq_url).hostname
        if rabbitmq_host in {"localhost", "127.0.0.1", "rabbitmq"}:
            errors.append("RABBITMQ_URL must use the deployed broker in production")

        if errors:
            raise ValueError("; ".join(errors))

        return self

    @property
    def sqlalchemy_database_url(self) -> str:
        if self.neon_postgres_url.startswith("postgresql://"):
            return self.neon_postgres_url.replace("postgresql://", "postgresql+psycopg://", 1)

        if self.neon_postgres_url.startswith("postgres://"):
            return self.neon_postgres_url.replace("postgres://", "postgresql+psycopg://", 1)

        return self.neon_postgres_url


@lru_cache
def get_settings() -> Settings:
    return Settings()