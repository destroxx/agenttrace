"""Data model for a recorded execution.

These are plain dataclasses rather than ORM or pydantic types: the SDK runs
inside the user's agent process and must stay dependency-free. The API owns its
own representation of the same concepts.
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import Any


def _now() -> datetime:
    return datetime.now(UTC)


def _new_id() -> str:
    return str(uuid.uuid4())


@dataclass(slots=True)
class ToolCall:
    """A single tool invocation and the response it produced."""

    name: str
    arguments: dict[str, Any]
    response: Any = None
    id: str = field(default_factory=_new_id)
    recorded_at: datetime = field(default_factory=_now)


@dataclass(slots=True)
class Trace:
    """One recorded agent execution."""

    name: str
    id: str = field(default_factory=_new_id)
    started_at: datetime = field(default_factory=_now)
    ended_at: datetime | None = None
    metadata: dict[str, Any] = field(default_factory=dict)
    tool_calls: list[ToolCall] = field(default_factory=list)

    @property
    def is_open(self) -> bool:
        """True while the trace is still accepting tool calls."""
        return self.ended_at is None

    def add_tool_call(self, call: ToolCall) -> None:
        """Append a tool call, refusing writes to a finished trace."""
        if not self.is_open:
            raise RuntimeError(f"trace {self.id} is already closed")
        self.tool_calls.append(call)

    def close(self) -> None:
        """Mark the trace finished."""
        if not self.is_open:
            raise RuntimeError(f"trace {self.id} is already closed")
        self.ended_at = _now()
