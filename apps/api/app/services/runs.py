"""Business logic for runs."""

from __future__ import annotations

import uuid
from datetime import UTC, datetime

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.project import Project
from app.models.run import Run, RunStatus
from app.schemas.run import RunComplete, RunCreate
from app.services.exceptions import ConflictError, NotFoundError
from app.services.pagination import Pagination


class RunService:
    """Starts, reads and finishes runs."""

    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def create(self, project_id: uuid.UUID, data: RunCreate) -> Run:
        """Start a run against a project.

        A run always begins as `running`; the caller cannot choose otherwise.
        """
        if await self._session.get(Project, project_id) is None:
            raise NotFoundError("Project", project_id)

        run = Run(
            project_id=project_id,
            agent_name=data.agent_name,
            agent_version=data.agent_version,
            input=data.input,
            status=RunStatus.RUNNING,
        )
        self._session.add(run)
        await self._session.flush()
        await self._session.refresh(run)
        await self._session.commit()
        return run

    async def get(self, run_id: uuid.UUID) -> Run:
        """Return one run, or raise `NotFoundError`."""
        run = await self._session.get(Run, run_id)
        if run is None:
            raise NotFoundError("Run", run_id)
        return run

    async def list_for_project(
        self, project_id: uuid.UUID, pagination: Pagination
    ) -> tuple[list[Run], int]:
        """Return one page of a project's runs, newest first."""
        if await self._session.get(Project, project_id) is None:
            raise NotFoundError("Project", project_id)

        total = await self._session.scalar(
            select(func.count()).select_from(Run).where(Run.project_id == project_id)
        )
        result = await self._session.scalars(
            select(Run)
            .where(Run.project_id == project_id)
            .order_by(Run.created_at.desc(), Run.id)
            .offset(pagination.offset)
            .limit(pagination.limit)
        )
        return list(result), int(total or 0)

    async def complete(self, run_id: uuid.UUID, data: RunComplete) -> Run:
        """Finish a run, recording its output and final status.

        A run that has already finished is not re-completed: overwriting the
        output of a recorded trace would silently destroy the thing AgentTrace
        exists to preserve.
        """
        run = await self.get(run_id)
        if run.is_terminal:
            raise ConflictError(
                f"Run {run_id} already finished with status {run.status!r}."
            )

        run.output = data.output
        run.status = data.status
        run.completed_at = datetime.now(UTC)

        await self._session.flush()
        await self._session.refresh(run)
        await self._session.commit()
        return run
