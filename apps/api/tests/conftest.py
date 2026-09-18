"""Shared test fixtures.

Two tiers of test run here:

* Unit tests build the app and stub the database session. They need no
  infrastructure.
* API tests run against a real PostgreSQL database named `<db>_test`, created
  and migrated once per session with the project's own Alembic migrations --
  so every run also proves the migrations still build a working schema from
  empty. Each test executes inside a transaction that is rolled back
  afterwards, so tests never see each other's rows.

If PostgreSQL is unreachable the database-backed tests skip with a clear
reason rather than failing; `RUN_INTEGRATION_TESTS=1` turns that skip into an
error, which is what CI should set.
"""

from __future__ import annotations

import asyncio
import os
import subprocess
import sys
from collections.abc import AsyncIterator, Iterator
from pathlib import Path

import pytest
from fastapi import FastAPI
from httpx import ASGITransport, AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession, create_async_engine
from sqlalchemy.pool import NullPool

API_ROOT = Path(__file__).resolve().parents[1]
ALEMBIC = Path(sys.executable).parent / "alembic"


def _ensure_credentials() -> None:
    """Guarantee settings can load, without overriding real local config.

    A developer's `apps/api/.env` supplies the real password, and pydantic
    reads it. Only when nothing supplies one -- a fresh checkout, a CI box
    running unit tests alone -- is a placeholder injected.
    """
    if os.environ.get("POSTGRES_PASSWORD"):
        return
    env_file = API_ROOT / ".env"
    if env_file.exists() and "POSTGRES_PASSWORD=" in env_file.read_text():
        return
    os.environ["POSTGRES_PASSWORD"] = "placeholder-for-unit-tests"


_ensure_credentials()


@pytest.fixture(autouse=True)
def _pinned_environment(monkeypatch: pytest.MonkeyPatch) -> Iterator[None]:
    """Pin settings-relevant environment variables for every test."""
    from app.config import get_settings

    monkeypatch.setenv("ENVIRONMENT", "ci")
    monkeypatch.setenv("DEBUG", "false")
    # POSTGRES_* must stay authoritative so tests cannot be pointed at a real
    # database by an ambient DATABASE_URL.
    monkeypatch.delenv("DATABASE_URL", raising=False)
    monkeypatch.setenv("POSTGRES_DB", _test_database_name())
    get_settings.cache_clear()
    yield
    get_settings.cache_clear()


def _test_database_name() -> str:
    """The dedicated database this suite owns."""
    return os.environ.get("POSTGRES_TEST_DB", "agenttrace_test")


def _admin_dsn() -> str:
    """An asyncpg DSN for the `postgres` maintenance database."""
    from app.config import Settings

    settings = Settings()  # type: ignore[call-arg]
    password = settings.postgres_password
    secret = password.get_secret_value() if password else ""
    return (
        f"postgres://{settings.postgres_user}:{secret}"
        f"@{settings.postgres_host}:{settings.postgres_port}/postgres"
    )


async def _provision(dsn: str, name: str) -> None:
    """Create the test database if it is not already there."""
    import asyncpg

    connection = await asyncpg.connect(dsn, timeout=5)
    try:
        exists = await connection.fetchval(
            "SELECT 1 FROM pg_database WHERE datname = $1", name
        )
        if not exists:
            # CREATE DATABASE cannot run inside a transaction block.
            await connection.execute(f'CREATE DATABASE "{name}"')
    finally:
        await connection.close()


@pytest.fixture(scope="session")
def migrated_database() -> str:
    """Create and migrate the test database once; return its async URL."""
    name = _test_database_name()
    strict = os.environ.get("RUN_INTEGRATION_TESTS") == "1"

    try:
        asyncio.run(_provision(_admin_dsn(), name))
    except Exception as exc:  # noqa: BLE001 - any failure means "no database"
        message = f"PostgreSQL is not reachable ({type(exc).__name__}: {exc})."
        if strict:
            pytest.fail(message)
        pytest.skip(f"{message} Start it with `docker compose up -d`.")

    # Build the schema the same way production does: through the migrations.
    result = subprocess.run(
        [str(ALEMBIC), "upgrade", "head"],
        cwd=API_ROOT,
        env={**os.environ, "POSTGRES_DB": name, "ENVIRONMENT": "ci"},
        capture_output=True,
        text=True,
        check=False,  # handled below, with the migration output attached
    )
    if result.returncode != 0:
        pytest.fail(f"alembic upgrade head failed:\n{result.stdout}\n{result.stderr}")

    from app.config import Settings, get_settings

    get_settings.cache_clear()
    os.environ["POSTGRES_DB"] = name
    return Settings().sqlalchemy_url  # type: ignore[call-arg]


@pytest.fixture
async def db_session(migrated_database: str) -> AsyncIterator[AsyncSession]:
    """A session wrapped in a transaction that is rolled back after the test.

    `join_transaction_mode="create_savepoint"` lets application code call
    `commit()` normally -- it releases a savepoint -- while the outer
    transaction below still undoes everything the test wrote.
    """
    engine = create_async_engine(migrated_database, poolclass=NullPool)
    connection = await engine.connect()
    transaction = await connection.begin()
    session = AsyncSession(
        bind=connection,
        expire_on_commit=False,
        join_transaction_mode="create_savepoint",
    )
    try:
        yield session
    finally:
        await session.close()
        await transaction.rollback()
        await connection.close()
        await engine.dispose()


@pytest.fixture
def app() -> FastAPI:
    """A freshly built application instance with no database wiring."""
    from app.main import create_app

    return create_app()


@pytest.fixture
async def client(app: FastAPI) -> AsyncIterator[AsyncClient]:
    """An HTTP client bound directly to the ASGI app (no network involved)."""
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://testserver") as client:
        yield client


@pytest.fixture
async def api_client(
    app: FastAPI, db_session: AsyncSession
) -> AsyncIterator[AsyncClient]:
    """An HTTP client whose requests run against the transactional test session."""
    from app.db.session import get_session

    async def _override() -> AsyncIterator[AsyncSession]:
        yield db_session

    app.dependency_overrides[get_session] = _override
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://testserver") as client:
        yield client
    app.dependency_overrides.clear()
