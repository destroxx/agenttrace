"""Business logic for events."""

from __future__ import annotations

import uuid

from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.event import Event
from app.models.run import Run
from app.schemas.event import EventCreate
from app.services.exceptions import ConflictError, NotFoundError


class EventService:
    """Appends events to a run and reads them back in order."""

    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def create(self, run_id: uuid.UUID, data: EventCreate) -> Event:
        """Append one event to a run.

        A finished run is a frozen recording: accepting a late event would
        change a trace that something has already been replayed or compared
        against. The run row is locked for the rest of the transaction so that
        this check cannot be overtaken by a concurrent `RunService.complete` --
        without the lock, both could read `running` and both succeed, leaving
        an event stamped after the run was closed.
        """
        run = await self._session.get(Run, run_id, with_for_update=True)
        if run is None:
            raise NotFoundError("Run", run_id)
        if run.is_terminal:
            raise ConflictError(
                f"Run {run_id} already finished with status {run.status!r}; "
                "its event stream is frozen."
            )

        event = Event(
            run_id=run_id,
            sequence=data.sequence,
            event_type=data.event_type,
            tool_name=data.tool_name,
            arguments=data.arguments,
            response=data.response,
            duration_ms=data.duration_ms,
        )
        self._session.add(event)
        try:
            await self._session.flush()
            await self._session.refresh(event)
            await self._session.commit()
        except IntegrityError as exc:
            await self._session.rollback()
            # The only uniqueness rule on events is (run_id, sequence).
            raise ConflictError(
                f"Run {run_id} already has an event at sequence {data.sequence}."
            ) from exc
        return event

    async def list_for_run(self, run_id: uuid.UUID) -> list[Event]:
        """Return every event of a run, ordered by `sequence` ascending.

        Not paginated, deliberately: a trace is only meaningful whole, and
        replay will consume the entire ordered sequence.
        """
        if await self._session.get(Run, run_id) is None:
            raise NotFoundError("Run", run_id)

        result = await self._session.scalars(
            select(Event).where(Event.run_id == run_id).order_by(Event.sequence.asc())
        )
        return list(result)
