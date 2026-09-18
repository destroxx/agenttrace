"""Health-check business logic.

Route handlers stay thin: they resolve dependencies and translate the report
below into an HTTP status code. Deciding *what* healthy means lives here.
"""

from __future__ import annotations

import asyncio
import time

from sqlalchemy import text
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.ext.asyncio import AsyncSession

from app import __version__
from app.config import Settings
from app.schemas.health import ComponentHealth, HealthReport


class HealthService:
    """Probes the API's dependencies and summarises the result."""

    def __init__(self, session: AsyncSession, settings: Settings) -> None:
        self._session = session
        self._settings = settings

    async def check(self) -> HealthReport:
        """Return the aggregate health report."""
        database = await self._check_database()
        overall = "ok" if database.status == "up" else "degraded"
        return HealthReport(
            status=overall,
            version=__version__,
            environment=self._settings.environment,
            checks={"database": database},
        )

    async def _check_database(self) -> ComponentHealth:
        """Issue a trivial query to confirm the database answers."""
        started = time.perf_counter()
        try:
            await asyncio.wait_for(
                self._session.execute(text("SELECT 1")),
                timeout=self._settings.health_check_timeout_seconds,
            )
        except TimeoutError:
            return ComponentHealth(
                status="down",
                error=(
                    "database probe timed out after "
                    f"{self._settings.health_check_timeout_seconds}s"
                ),
            )
        except (SQLAlchemyError, OSError) as exc:
            return ComponentHealth(status="down", error=_summarise(exc))

        elapsed_ms = (time.perf_counter() - started) * 1000
        return ComponentHealth(status="up", latency_ms=round(elapsed_ms, 2))


def _summarise(exc: BaseException) -> str:
    """Render an exception without leaking the DSN (which carries the password)."""
    return f"{type(exc).__name__}: {str(exc).splitlines()[0][:200]}"
