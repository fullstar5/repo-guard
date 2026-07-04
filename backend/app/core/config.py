from functools import lru_cache
from pathlib import Path

from pydantic_settings import BaseSettings, SettingsConfigDict

BASE_DIR = Path(__file__).resolve().parents[2]


class Settings(BaseSettings):
    neon_postgres_url: str
    upstash_redis_rest_url: str
    upstash_redis_rest_token: str

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