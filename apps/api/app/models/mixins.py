"""Column mixins shared by every model."""

from __future__ import annotations

import uuid
from datetime import datetime

from sqlalchemy import DateTime, func
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column


class UUIDPrimaryKeyMixin:
    """A UUID v4 primary key generated client-side.

    Generating in Python rather than with a server default lets a caller know
    an entity's id before it is flushed — which matters for the SDK, where a
    trace and its events are built up in memory before anything is sent.
    """

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        primary_key=True,
        default=uuid.uuid4,
        # Mixin columns are appended by default; pin the key to the front so
        # every table reads id-first.
        sort_order=-100,
    )


class TimestampMixin:
    """Creation and update timestamps, both timezone-aware."""

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        nullable=False,
        sort_order=100,
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        onupdate=func.now(),
        nullable=False,
        sort_order=100,
    )
