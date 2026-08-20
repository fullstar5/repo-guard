from functools import lru_cache
from pathlib import Path

from pydantic_settings import BaseSettings, SettingsConfigDict  # pyright: ignore[reportMissingImports]

BASE_DIR = Path(__file__).resolve().parents[2]


class Settings(BaseSettings):
    neon_postgres_url: str
    upstash_redis_rest_url: str
    upstash_redis_rest_token: str

    github_client_id: str
    github_client_secret: str
    github_redirect_uri: str

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
    openrouter_read_timeout: float = 120.0

    # Use larger defaults for debugging single-request review behavior first.
    review_max_combined_chars: int = 120000
    review_max_patch_chars: int = 20000
    review_max_combined_files: int = 30
    review_max_combined_changes: int = 1000
    review_retry_attempts: int = 3


    # RabbitMQ and celery
    rabbitmq_url: str = "amqp://guest:guest@localhost:5672//"
    celery_result_backend: str = "rpc://"

    celery_task_max_retries: int = 3
    celery_task_retry_backoff_seconds: int = 5   # wait for x second before next try
    celery_task_retry_backoff_max: int = 300   #
    celery_task_soft_time_limit: int = 660   # allow graceful failure handling before hard kill
    celery_task_time_limit: int = 720   # hard stop on job if exceed this time

    celery_task_reclaim_interval_seconds: float = 600   # auto mark stale jobs as failed
    review_job_stale_processing_seconds: int = 900   # if a job stays in 'processing' longer than this, abandoned


    model_config = SettingsConfigDict(
        env_file=BASE_DIR / ".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )

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