"""The Run model: one recorded execution of an agent."""

from __future__ import annotations

import uuid
from datetime import datetime
from enum import StrEnum
from typing import TYPE_CHECKING, Any

from sqlalchemy import (
    CheckConstraint,
    DateTime,
    ForeignKey,
    Index,
    String,
    func,
)
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base
from app.models.mixins import UUIDPrimaryKeyMixin

if TYPE_CHECKING:
    from app.models.event import Event
    from app.models.project import Project


class RunStatus(StrEnum):
    """The states a run can be in.

    Three values, deliberately. A run is recording, it finished, or it blew up.
    """

    RUNNING = "running"
    COMPLETED = "completed"
    FAILED = "failed"

    @classmethod
    def terminal(cls) -> frozenset[RunStatus]:
        """States from which a run accepts no further updates."""
        return frozenset({cls.COMPLETED, cls.FAILED})


class Run(UUIDPrimaryKeyMixin, Base):
    """One execution of an agent, owned by a project and owning many events."""

    __tablename__ = "runs"
    __table_args__ = (
        CheckConstraint(
            "status IN ('running', 'completed', 'failed')",
            name="status_valid",
        ),
        Index("ix_runs_project_id_created_at", "project_id", "created_at"),
    )

    project_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("projects.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )

    agent_name: Mapped[str] = mapped_column(String(255), nullable=False)
    agent_version: Mapped[str | None] = mapped_column(String(64), nullable=True)

    # JSONB, not a rigid column set: every agent takes and returns a different
    # shape, and AgentTrace must record them all without a schema migration.
    input: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False)
    output: Mapped[dict[str, Any] | None] = mapped_column(JSONB, nullable=True)

    status: Mapped[str] = mapped_column(
        String(32),
        nullable=False,
        default=RunStatus.RUNNING,
        server_default=RunStatus.RUNNING.value,
    )

    started_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        nullable=False,
    )
    completed_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True),
        nullable=True,
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        nullable=False,
        index=True,
    )

    project: Mapped[Project] = relationship(back_populates="runs")
    events: Mapped[list[Event]] = relationship(
        back_populates="run",
        cascade="all, delete-orphan",
        passive_deletes=True,
        # Rule 2: a run's events are only ever meaningful in sequence order.
        order_by="Event.sequence",
    )

    @property
    def is_terminal(self) -> bool:
        """True once the run has finished, successfully or not."""
        return self.status in RunStatus.terminal()

    def __repr__(self) -> str:
        return f"Run(id={self.id!r}, agent={self.agent_name!r}, status={self.status!r})"
