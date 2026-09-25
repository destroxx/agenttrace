"""The Comparison model: the verdict on one replay, as the SDK computed it."""

from __future__ import annotations

import uuid
from datetime import datetime
from typing import Any

from sqlalchemy import CheckConstraint, DateTime, ForeignKey, String, func
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base
from app.models.mixins import UUIDPrimaryKeyMixin


class Comparison(UUIDPrimaryKeyMixin, Base):
    """A stored `ComparisonReport` for one replay run.

    The API does not compare anything. Comparison runs in the SDK, next to the
    agent, where CI needs its verdict; this row only keeps the result so the
    dashboard can show it. `verdict` is copied out of `report` into its own
    column so run lists can show it with a join instead of reading JSON.
    """

    __tablename__ = "comparisons"
    __table_args__ = (
        CheckConstraint("verdict IN ('pass', 'fail')", name="verdict_valid"),
    )

    # Unique: a replay run has exactly one report, and reports are immutable
    # like the runs they describe. The unique index also serves the lookup of
    # a run's report and the join from the run list.
    replay_run_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("runs.id", ondelete="CASCADE"),
        nullable=False,
        unique=True,
    )
    # CASCADE on both: a report without either run it compares cannot be read
    # meaningfully, and keeping it would leave a verdict pointing at nothing.
    recording_run_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("runs.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )

    verdict: Mapped[str] = mapped_column(String(16), nullable=False)
    # The SDK's `ComparisonReport.to_dict()`, verbatim. JSONB rather than
    # columns per finding: the report's shape belongs to the SDK and will grow
    # (Phase 7 suites), and the dashboard only ever reads it whole.
    report: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False)

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        nullable=False,
    )

    def __repr__(self) -> str:
        return f"Comparison(replay_run_id={self.replay_run_id!r}, verdict={self.verdict!r})"
