"""The Event model: one step inside a recorded agent run."""

from __future__ import annotations

import uuid
from datetime import datetime
from enum import StrEnum
from typing import TYPE_CHECKING, Any

from sqlalchemy import (
    DateTime,
    ForeignKey,
    Index,
    Integer,
    String,
    UniqueConstraint,
    func,
)
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base
from app.models.mixins import UUIDPrimaryKeyMixin

if TYPE_CHECKING:
    from app.models.run import Run


class EventType(StrEnum):
    """The event types AgentTrace itself understands.

    Not a database constraint: `event_type` is a free string so an SDK can
    record a kind of step this list has not anticipated. These are the values
    the platform gives meaning to.
    """

    AGENT_START = "agent_start"
    TOOL_CALL = "tool_call"
    TOOL_RESPONSE = "tool_response"
    AGENT_END = "agent_end"
    ERROR = "error"


class Event(UUIDPrimaryKeyMixin, Base):
    """A single step within a run, ordered by `sequence`."""

    __tablename__ = "events"
    __table_args__ = (
        # Replay depends on a total, gap-free-enough ordering of a run's
        # events. Making (run_id, sequence) unique is what stops two events
        # from ever claiming the same position, and the index it creates is
        # also the one that serves "fetch this run's events in order".
        UniqueConstraint("run_id", "sequence", name="uq_events_run_id_sequence"),
        # Replay pairs a tool_call with the tool_response that answered it by
        # looking both up under one call id. Not unique: a call and its
        # response deliberately share the value.
        Index("ix_events_run_id_call_id", "run_id", "call_id"),
    )

    run_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("runs.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )

    sequence: Mapped[int] = mapped_column(Integer, nullable=False)
    event_type: Mapped[str] = mapped_column(String(64), nullable=False)

    # A string rather than a UUID: the id is minted by whatever produced the
    # call, and other SDKs and model providers use their own formats
    # (OpenAI's "call_abc123", for instance). Storing it verbatim keeps the
    # recording faithful to what actually happened.
    call_id: Mapped[str | None] = mapped_column(String(255), nullable=True)

    tool_name: Mapped[str | None] = mapped_column(String(255), nullable=True)
    arguments: Mapped[dict[str, Any] | None] = mapped_column(JSONB, nullable=True)
    response: Mapped[Any | None] = mapped_column(JSONB, nullable=True)

    duration_ms: Mapped[int | None] = mapped_column(Integer, nullable=True)

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        nullable=False,
    )

    run: Mapped[Run] = relationship(back_populates="events")

    def __repr__(self) -> str:
        return (
            f"Event(id={self.id!r}, seq={self.sequence!r}, type={self.event_type!r})"
        )
