"""Business logic for runs."""

from __future__ import annotations

import uuid
from datetime import UTC, datetime

from sqlalchemy import func, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.event import Event
from app.models.project import Project
from app.models.run import Run, RunStatus
from app.schemas.run import RunComplete, RunCreate, RunIngest
from app.services.exceptions import ConflictError, NotFoundError
from app.services.pagination import Pagination


def _violated_constraint(exc: IntegrityError) -> str | None:
    """Name the constraint an IntegrityError tripped, if the driver says.

    The driver's exception is wrapped more than once on the way up, and only
    the innermost one carries `constraint_name`. Reading it lets a caller map
    exactly one violation onto a domain error instead of assuming every
    integrity failure means the same thing.
    """
    error: BaseException | None = exc.orig
    while error is not None:
        name = getattr(error, "constraint_name", None)
        if name:
            return str(name)
        error = error.__cause__
    return None


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

    async def ingest(self, project_id: uuid.UUID, data: RunIngest) -> Run:
        """Store one already-finished run and its whole trace at once.

        This is the SDK's upload path: it buffers an execution in memory and
        sends it here when the agent stops. The run and every event are written
        in a single transaction, because a half-stored trace is worse than none
        -- replay would read it as a complete recording of an agent that
        stopped early, and compare against it.

        No row lock is taken: the run does not exist yet, so there is nothing
        to serialize against. The primary key is what makes a retried upload
        safe.
        """
        if await self._session.get(Project, project_id) is None:
            raise NotFoundError("Project", project_id)

        run = Run(
            id=data.id,
            project_id=project_id,
            agent_name=data.agent_name,
            agent_version=data.agent_version,
            input=data.input,
            output=data.output,
            status=data.status,
            started_at=data.started_at,
            completed_at=data.completed_at,
            run_metadata=data.metadata,
            events=[
                Event(
                    sequence=event.sequence,
                    event_type=event.event_type,
                    call_id=event.call_id,
                    tool_name=event.tool_name,
                    arguments=event.arguments,
                    response=event.response,
                    duration_ms=event.duration_ms,
                )
                for event in data.events
            ],
        )
        self._session.add(run)
        try:
            await self._session.flush()
            await self._session.refresh(run)
            await self._session.commit()
        except IntegrityError as exc:
            await self._session.rollback()
            if _violated_constraint(exc) == "pk_runs":
                raise ConflictError(f"Run {data.id} already exists.") from exc
            # Anything else is not a retried upload; let it surface rather
            # than reporting a misleading conflict.
            raise
        return run

    async def complete(self, run_id: uuid.UUID, data: RunComplete) -> Run:
        """Finish a run, recording its output and final status.

        A run that has already finished is not re-completed: overwriting the
        output of a recorded trace would silently destroy the thing AgentTrace
        exists to preserve.

        The row is locked rather than read through `get`, so that closing a run
        and appending an event to it are serialized against each other. Whoever
        takes the lock second sees the other's committed state and conflicts,
        instead of both deciding on the same stale `running`.
        """
        run = await self._session.get(Run, run_id, with_for_update=True)
        if run is None:
            raise NotFoundError("Run", run_id)
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
