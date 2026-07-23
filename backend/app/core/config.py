from functools import lru_cache
from pathlib import Path

from pydantic_settings import BaseSettings, SettingsConfigDict

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

    jwt_secret_key: str
    jwt_algorithm: str
    access_token_expire_minutes: int

    open_router_api_key: str
    open_router_base_url: str = "https://openrouter.ai/api/v1"
    open_router_default_model: str = "openrouter/free"
    app_public_url: str = "http://localhost:3000"
    app_name: str = "CodeGuard AI"

    # Use larger defaults for debugging single-request review behavior first.
    review_max_combined_chars: int = 120000
    review_max_patch_chars: int = 20000
    review_max_combined_files: int = 30
    review_max_combined_changes: int = 1000
    review_retry_attempts: int = 3

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