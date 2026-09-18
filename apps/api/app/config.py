"""Application configuration.

All configuration is sourced from the environment (optionally via a local
`.env` file). Nothing in this module carries a production-usable default for a
credential: if a secret is missing, startup fails loudly rather than silently
falling back.
"""

from __future__ import annotations

from functools import lru_cache
from typing import Literal

from pydantic import Field, SecretStr
from pydantic_settings import BaseSettings, SettingsConfigDict

Environment = Literal["local", "ci", "staging", "production"]


class Settings(BaseSettings):
    """Runtime settings for the AgentTrace API."""

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
        case_sensitive=False,
    )

    environment: Environment = "local"
    debug: bool = False

    api_host: str = "0.0.0.0"
    api_port: int = 8000

    postgres_host: str = "localhost"
    postgres_port: int = 5432
    postgres_db: str = "agenttrace"
    postgres_user: str = "agenttrace"
    postgres_password: SecretStr = Field(
        ...,
        description="Database password. Required; never defaulted in code.",
    )

    # Origins permitted to call the API from a browser. The web app runs on
    # :3000 in development; production origins come from the environment.
    cors_allow_origins: list[str] = ["http://localhost:3000"]

    # Number of seconds a health probe waits on the database before giving up.
    health_check_timeout_seconds: float = 3.0

    @property
    def database_url(self) -> str:
        """SQLAlchemy async DSN assembled from the discrete Postgres settings.

        Deliberately a plain property rather than a `computed_field`: a
        computed field is included in `repr()` and `model_dump()`, which would
        leak the password into logs and error reports.
        """
        password = self.postgres_password.get_secret_value()
        return (
            f"postgresql+asyncpg://{self.postgres_user}:{password}"
            f"@{self.postgres_host}:{self.postgres_port}/{self.postgres_db}"
        )


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    """Return the process-wide settings instance.

    Cached so that configuration is parsed and validated exactly once. Tests
    clear the cache via `get_settings.cache_clear()` after changing the
    environment.
    """
    return Settings()  # type: ignore[call-arg]
