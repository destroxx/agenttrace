"""The Project model: one application whose agent runs are being recorded."""

from __future__ import annotations

from typing import TYPE_CHECKING

from sqlalchemy import String, Text
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base
from app.models.mixins import TimestampMixin, UUIDPrimaryKeyMixin

if TYPE_CHECKING:
    from app.models.run import Run


class Project(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    """One AgentTrace project. Owns many runs."""

    __tablename__ = "projects"

    name: Mapped[str] = mapped_column(String(255), nullable=False)
    description: Mapped[str | None] = mapped_column(Text, nullable=True)

    runs: Mapped[list[Run]] = relationship(
        back_populates="project",
        cascade="all, delete-orphan",
        # The database owns the cascade (ON DELETE CASCADE); passive_deletes
        # stops SQLAlchemy from loading every child row just to delete it.
        passive_deletes=True,
        order_by="Run.created_at.desc()",
    )

    def __repr__(self) -> str:
        return f"Project(id={self.id!r}, name={self.name!r})"
