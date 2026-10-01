"""The ApiKey model: a credential that may write to exactly one project."""

from __future__ import annotations

import uuid
from datetime import datetime

from sqlalchemy import DateTime, ForeignKey, String, func
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base
from app.models.mixins import UUIDPrimaryKeyMixin


class ApiKey(UUIDPrimaryKeyMixin, Base):
    """One project's API key, stored as a hash.

    The key itself exists only in the response that created it. A plain
    SHA-256 rather than a slow password hash: keys are 256 random bits, so
    there is nothing for a dictionary attack to guess, and a fast hash keeps
    authentication to one indexed lookup per request.
    """

    __tablename__ = "api_keys"

    # CASCADE: a key for a project that no longer exists can write nowhere.
    project_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("projects.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    name: Mapped[str | None] = mapped_column(String(255), nullable=True)

    # The key's first characters, kept so a person can tell keys apart in a
    # list without the list revealing anything usable.
    prefix: Mapped[str] = mapped_column(String(16), nullable=False)
    # Unique: authentication looks a key up by its hash, and the index is that
    # lookup.
    key_hash: Mapped[str] = mapped_column(String(64), nullable=False, unique=True)

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        nullable=False,
    )
    # Set once, never cleared. A revoked key stays as a row, so the list still
    # shows which key was used and when it stopped working.
    revoked_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True),
        nullable=True,
    )

    @property
    def is_revoked(self) -> bool:
        return self.revoked_at is not None

    def __repr__(self) -> str:
        # The hash stays out of reprs and logs, like every other secret here.
        return f"ApiKey(id={self.id!r}, project_id={self.project_id!r}, prefix={self.prefix!r})"
