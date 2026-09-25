"""Business logic for runs."""

from __future__ import annotations

import uuid
from collections.abc import Sequence
from datetime import UTC, datetime

from sqlalchemy import BigInteger, Row, func, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.comparison import Comparison
from app.models.event import Event
from app.models.project import Project
from app.models.run import Run, RunStatus
from app.schemas.run import RunComplete, RunCreate, RunIngest
from app.services.exceptions import ConflictError, NotFoundError, UnprocessableError
from app.services.pagination import Pagination


def violated_constraint(exc: IntegrityError) -> str | None:
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


def _foreign_recording(run_id: uuid.UUID, project_id: uuid.UUID) -> UnprocessableError:
    return UnprocessableError(
        "replay_of_run_id",
        f"replay_of_run_id {run_id} is not a run in project {project_id}.",
    )


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
        self,
        project_id: uuid.UUID,
        pagination: Pagination,
        status: RunStatus | None = None,
    ) -> tuple[Sequence[Row[tuple[Run, int, int | None, str | None]]], int]:
        """Return one page of a project's runs, newest first, with list-only facts.

        Each row is `(run, event_count, duration_ms, verdict)`. They are
        computed by the same query that pages the runs -- a correlated count
        served by the events' run_id index, and a join to the run's report --
        so a page costs a fixed number of queries however many runs it holds.
        Reading them per run would be one query per row, and a dashboard asks
        for this page on every visit.

        `duration_ms` is wall-clock time from the client's own timestamps, so
        it is only as good as that clock; it is None while a run is running.
        """
        if await self._session.get(Project, project_id) is None:
            raise NotFoundError("Project", project_id)

        conditions = [Run.project_id == project_id]
        if status is not None:
            conditions.append(Run.status == status)

        event_count = (
            select(func.count(Event.id))
            .where(Event.run_id == Run.id)
            .correlate(Run)
            .scalar_subquery()
        )
        duration_ms = func.floor(
            func.extract("epoch", Run.completed_at - Run.started_at) * 1000
        ).cast(BigInteger)

        total = await self._session.scalar(
            select(func.count()).select_from(Run).where(*conditions)
        )
        result = await self._session.execute(
            select(
                Run,
                event_count.label("event_count"),
                duration_ms.label("duration_ms"),
                Comparison.verdict.label("verdict"),
            )
            .outerjoin(Comparison, Comparison.replay_run_id == Run.id)
            .where(*conditions)
            .order_by(Run.created_at.desc(), Run.id)
            .offset(pagination.offset)
            .limit(pagination.limit)
        )
        return result.all(), int(total or 0)

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

        A replay names the recording it replayed. That recording must live in
        the same project: a replay compared against another project's run
        would be a cross-tenant read the moment authentication exists. An
        unknown id and a foreign one get the same answer, so the error does
        not reveal which run ids exist elsewhere.
        """
        if await self._session.get(Project, project_id) is None:
            raise NotFoundError("Project", project_id)
        if data.replay_of_run_id is not None:
            recording = await self._session.get(Run, data.replay_of_run_id)
            if recording is None or recording.project_id != project_id:
                raise _foreign_recording(data.replay_of_run_id, project_id)

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
            replay_of_run_id=data.replay_of_run_id,
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
            violated = violated_constraint(exc)
            if violated == "pk_runs":
                raise ConflictError(f"Run {data.id} already exists.") from exc
            if violated == "fk_runs_replay_of_run_id_runs":
                # The recording was deleted between the check above and the
                # insert; answer as if the check had seen it gone.
                raise _foreign_recording(data.replay_of_run_id, project_id) from exc
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
