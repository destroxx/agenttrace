"""Tests for configuration loading.

These build `Settings` explicitly with `_env_file=None` so they assert on
configuration *logic* and stay deterministic regardless of what is in the
ambient environment.
"""

from __future__ import annotations

import pytest
from pydantic import ValidationError

from app.config import Settings, get_settings


def _settings(**overrides: object) -> Settings:
    values: dict[str, object] = {
        "postgres_host": "db.example",
        "postgres_port": 6543,
        "postgres_db": "traces",
        "postgres_user": "writer",
        "postgres_password": "s3cret",
    }
    values.update(overrides)
    return Settings(_env_file=None, **values)  # type: ignore[arg-type]


def test_dsn_is_assembled_from_components() -> None:
    assert _settings().sqlalchemy_url == (
        "postgresql+asyncpg://writer:s3cret@db.example:6543/traces"
    )


def test_password_special_characters_are_url_encoded() -> None:
    """A password containing DSN punctuation must not corrupt the URL."""
    url = _settings(postgres_password="p@ss/w:rd").sqlalchemy_url

    assert "p%40ss%2Fw%3Ard" in url
    assert url.endswith("@db.example:6543/traces")


def test_database_url_overrides_the_components() -> None:
    settings = _settings(DATABASE_URL="postgresql+asyncpg://u:p@other:5432/d")

    assert settings.sqlalchemy_url == "postgresql+asyncpg://u:p@other:5432/d"


@pytest.mark.parametrize(
    "given",
    [
        "postgresql://u:p@h:5432/d",
        "postgresql+psycopg://u:p@h:5432/d",
        "postgresql+psycopg2://u:p@h:5432/d",
    ],
)
def test_sync_dsn_is_coerced_onto_the_async_driver(given: str) -> None:
    """The stack is async end to end; a provider-issued sync DSN still works."""
    assert _settings(DATABASE_URL=given).sqlalchemy_url == (
        "postgresql+asyncpg://u:p@h:5432/d"
    )


def test_secrets_are_not_exposed_by_repr_or_dump() -> None:
    """Both the password and the full DSN carry credentials."""
    settings = _settings(DATABASE_URL="postgresql://u:topsecret@h/d")

    assert "s3cret" not in repr(settings)
    assert "topsecret" not in repr(settings)
    assert "topsecret" not in str(settings.model_dump())
    assert settings.postgres_password is not None
    assert settings.postgres_password.get_secret_value() == "s3cret"


def test_no_database_configuration_is_a_startup_error(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.delenv("POSTGRES_PASSWORD", raising=False)
    monkeypatch.delenv("DATABASE_URL", raising=False)

    with pytest.raises(ValidationError) as caught:
        Settings(_env_file=None)  # type: ignore[call-arg]

    assert "No database configuration found" in str(caught.value)


def test_database_url_alone_is_sufficient(monkeypatch: pytest.MonkeyPatch) -> None:
    """A single DSN is enough; the discrete POSTGRES_* values become optional."""
    monkeypatch.delenv("POSTGRES_PASSWORD", raising=False)

    settings = Settings(_env_file=None, DATABASE_URL="postgresql://u:p@h/d")  # type: ignore[call-arg]

    assert settings.sqlalchemy_url == "postgresql+asyncpg://u:p@h/d"


def test_environment_must_be_a_known_value() -> None:
    with pytest.raises(ValidationError):
        _settings(environment="prod-ish")


def test_defaults_target_local_development(monkeypatch: pytest.MonkeyPatch) -> None:
    """With nothing configured but the password, settings target local dev."""
    for key in ("ENVIRONMENT", "DEBUG", "POSTGRES_HOST", "POSTGRES_PORT", "POSTGRES_DB"):
        monkeypatch.delenv(key, raising=False)

    settings = Settings(_env_file=None, postgres_password="x")  # type: ignore[call-arg]

    assert settings.environment == "local"
    assert settings.debug is False
    assert settings.postgres_host == "localhost"
    assert settings.postgres_port == 5432


def test_settings_are_cached() -> None:
    assert get_settings() is get_settings()
