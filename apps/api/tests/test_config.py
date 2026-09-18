"""Tests for configuration loading.

These build `Settings` explicitly with `_env_file=None` so they assert on
configuration *logic* and stay deterministic regardless of what is in the
ambient environment (an integration run, for instance, injects real
credentials).
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


def test_database_url_is_assembled_from_components() -> None:
    assert _settings().database_url == (
        "postgresql+asyncpg://writer:s3cret@db.example:6543/traces"
    )


def test_password_is_not_exposed_by_repr_or_dump() -> None:
    """The DSN embeds the password, so it must stay out of serialised output."""
    settings = _settings()

    assert "s3cret" not in repr(settings)
    assert "s3cret" not in str(settings.model_dump())
    assert "database_url" not in settings.model_dump()
    assert settings.postgres_password.get_secret_value() == "s3cret"


def test_missing_password_is_a_startup_error(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("POSTGRES_PASSWORD", raising=False)
    with pytest.raises(ValidationError):
        Settings(_env_file=None)  # type: ignore[call-arg]


def test_environment_must_be_a_known_value() -> None:
    with pytest.raises(ValidationError):
        _settings(environment="prod-ish")


def test_defaults_target_local_development(monkeypatch: pytest.MonkeyPatch) -> None:
    """With nothing configured but the password, settings target local dev."""
    for key in ("ENVIRONMENT", "DEBUG", "POSTGRES_HOST", "POSTGRES_PORT"):
        monkeypatch.delenv(key, raising=False)

    settings = Settings(_env_file=None, postgres_password="x")  # type: ignore[call-arg]

    assert settings.environment == "local"
    assert settings.debug is False
    assert settings.postgres_host == "localhost"
    assert settings.postgres_port == 5432


def test_settings_are_cached() -> None:
    assert get_settings() is get_settings()
