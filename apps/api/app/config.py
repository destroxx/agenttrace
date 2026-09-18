"""Application configuration.

All configuration is sourced from the environment (optionally via a local
`.env` file). Nothing in this module carries a production-usable default for a
credential: if a secret is missing, startup fails loudly rather than silently
falling back.
"""

from __future__ import annotations

from functools import lru_cache
from typing import Literal
from urllib.parse import quote_plus

from pydantic import Field, SecretStr, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

Environment = Literal["local", "ci", "staging", "production"]

# Sync drivers a DATABASE_URL may legitimately name. The application stack is
# async end to end, so they are rewritten onto asyncpg rather than rejected --
# a hosting provider hands out "postgresql://..." and expects it to work.
_SYNC_PREFIXES = ("postgresql+psycopg://", "postgresql+psycopg2://", "postgresql://")


def _as_async_dsn(url: str) -> str:
    """Coerce a PostgreSQL DSN onto the asyncpg driver."""
    for prefix in _SYNC_PREFIXES:
        if url.startswith(prefix):
            return "postgresql+asyncpg://" + url[len(prefix) :]
    return url


class Settings(BaseSettings):
    """Runtime settings for the AgentTrace API."""

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
        case_sensitive=False,
        populate_by_name=True,
    )

    environment: Environment = "local"
    debug: bool = False

    api_host: str = "0.0.0.0"
    api_port: int = 8000

    postgres_host: str = "localhost"
    postgres_port: int = 5432
    postgres_db: str = "agenttrace"
    postgres_user: str = "agenttrace"
    postgres_password: SecretStr | None = Field(
        default=None,
        description="Database password. Never defaulted in code.",
    )

    # A full DSN, which takes precedence over the discrete settings above.
    # Managed Postgres providers and CI runners hand out one connection string
    # rather than five variables.
    database_url: SecretStr | None = Field(
        default=None,
        alias="DATABASE_URL",
        description="Full database DSN. Overrides the POSTGRES_* settings.",
    )

    # Origins permitted to call the API from a browser. The web app runs on
    # :3000 in development; production origins come from the environment.
    cors_allow_origins: list[str] = ["http://localhost:3000"]

    # Number of seconds a health probe waits on the database before giving up.
    health_check_timeout_seconds: float = 3.0

    @model_validator(mode="after")
    def _require_a_way_to_reach_the_database(self) -> Settings:
        """Fail at startup, with a usable message, if the database is unreachable by config."""
        if self.database_url is None and self.postgres_password is None:
            raise ValueError(
                "No database configuration found. Set DATABASE_URL, or set "
                "POSTGRES_PASSWORD (with the other POSTGRES_* settings). "
                "Copy apps/api/.env.example to apps/api/.env to get started."
            )
        return self

    @property
    def sqlalchemy_url(self) -> str:
        """The async DSN the engine and Alembic both connect with.

        Deliberately a plain property rather than a `computed_field`: a
        computed field is included in `repr()` and `model_dump()`, which would
        leak the password into logs and error reports.
        """
        if self.database_url is not None:
            return _as_async_dsn(self.database_url.get_secret_value())

        assert self.postgres_password is not None  # guaranteed by the validator
        password = quote_plus(self.postgres_password.get_secret_value())
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
