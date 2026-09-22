"""Data model for a recorded execution.

These are plain dataclasses rather than ORM or pydantic types: the SDK runs
inside the user's agent process and must stay dependency-free. The API owns its
own representation of the same concepts.
"""

from __future__ import annotations

import json
import logging
import threading
import uuid
from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import Any

logger = logging.getLogger("agenttrace")


def _now() -> datetime:
    return datetime.now(UTC)


def _new_id() -> str:
    return str(uuid.uuid4())


def snapshot(value: Any) -> Any:
    """Detach a value from the agent that produced it.

    Upload happens when the run ends, so anything recorded by reference can
    still be mutated afterwards -- an agent that reads a tool's dict and edits
    it in place would rewrite history, and the trace would no longer be what
    the tool actually returned. For a record/replay product that is fatal: the
    recording is the fixture every future comparison is measured against.

    The copy goes through JSON rather than `copy.deepcopy` because the value
    has to survive the upload anyway, so this also settles up front whether it
    can be serialised at all. `allow_nan=False` is deliberate: Python emits
    bare `NaN`/`Infinity`, which is not valid JSON and which the API would
    reject on arrival rather than here, where it can still be salvaged.

    A value that cannot be represented -- NaN, a circular reference, an object
    whose `default=str` still fails -- degrades to its `repr` rather than
    raising. A slightly lossy recording beats no recording, and beats an
    exception in someone else's agent.
    """
    if value is None:
        return None
    try:
        return json.loads(json.dumps(value, default=str, allow_nan=False))
    except Exception as exc:  # noqa: BLE001 - a custom __str__ may raise anything
        logger.warning(
            "agenttrace: value could not be snapshotted, recording its repr: %r", exc
        )
        return repr(value)


def as_json_object(value: Any) -> dict[str, Any] | None:
    """Coerce a run's input or output into the JSON object the API requires.

    `runs.input` and `runs.output` are typed as objects so they stay queryable
    in JSONB; a bare string or list would be rejected with a 422. Rather than
    make callers remember that, a non-mapping value is wrapped as
    `{"value": ...}` -- lossless, and obvious when read back.
    """
    if value is None:
        return None
    if isinstance(value, dict):
        return dict(value)
    return {"value": value}


def snapshot_object(value: Any) -> dict[str, Any] | None:
    """Snapshot a value that the API insists must be a JSON object.

    `input`, `output`, `metadata` and an event's `arguments` are all typed as
    objects. `snapshot` can degrade to a string, which would turn a valid
    payload into a 422, so a degraded result is wrapped back into an object
    instead of being sent as-is.
    """
    wrapped = as_json_object(value)
    if wrapped is None:
        return None
    taken = snapshot(wrapped)
    if isinstance(taken, dict):
        return taken
    return {"value": taken}


@dataclass(slots=True)
class ToolCall:
    """A single tool invocation and the response it produced.

    `arguments` and `response` hold the same snapshots as the matching events
    in `Trace.events`, taken at record time. There is one recording, and this
    is a view onto it: an agent that mutates a value a tool returned cannot
    change what either of them says.
    """

    name: str
    arguments: dict[str, Any]
    response: Any = None
    id: str = field(default_factory=_new_id)
    recorded_at: datetime = field(default_factory=_now)
    duration_ms: int | None = None
    # Set instead of `response` when the tool raised. The exception itself is
    # never stored: it is not JSON, and holding it would keep the failed call's
    # whole traceback frame alive for the life of the trace.
    error: str | None = None


@dataclass(slots=True)
class RecordedEvent:
    """One step of a trace, mirroring the API's `EventCreate` contract.

    Kept separate from `ToolCall` because a trace records more than tools --
    `agent_start`, `agent_end` and `error` have no call of their own -- and
    because this is the shape that goes on the wire. Its `arguments` and
    `response` are snapshots, detached from the agent's own objects.
    """

    sequence: int
    event_type: str
    call_id: str | None = None
    tool_name: str | None = None
    arguments: dict[str, Any] | None = None
    response: Any = None
    duration_ms: int | None = None


@dataclass(slots=True)
class Trace:
    """One recorded agent execution."""

    name: str
    id: str = field(default_factory=_new_id)
    started_at: datetime = field(default_factory=_now)
    ended_at: datetime | None = None
    metadata: dict[str, Any] = field(default_factory=dict)
    tool_calls: list[ToolCall] = field(default_factory=list)
    input: dict[str, Any] = field(default_factory=dict)
    output: dict[str, Any] | None = None
    agent_version: str | None = None
    status: str = "running"
    events: list[RecordedEvent] = field(default_factory=list)
    uploaded: bool = False
    # Set when this trace was recorded while replaying another run: the id of
    # that recording, so the API can link the replay back to it.
    replay_of_run_id: str | None = None
    # Sequence numbers are the total order replay depends on, and a sync tool
    # may be recorded from a worker thread, so the counter, the open/closed
    # check and the append that consumes them all happen together under this
    # lock. Without it two threads could take the same number, land in the list
    # out of order, or append to a trace that closed in between.
    _sequence: int = 0
    _lock: threading.Lock = field(default_factory=threading.Lock, repr=False)

    def __post_init__(self) -> None:
        """Detach the run's own payloads, for the reasons `snapshot` explains.

        Done here rather than in the tracer so that a `Trace` built directly --
        in a test, or by another recorder -- gets the same guarantee.
        """
        self.input = snapshot_object(self.input) or {}
        self.metadata = snapshot_object(self.metadata) or {}

    @property
    def is_open(self) -> bool:
        """True while the trace is still accepting tool calls."""
        return self.ended_at is None

    def add_tool_call(self, call: ToolCall) -> None:
        """Append a tool call, refusing writes to a finished trace."""
        with self._lock:
            if self.ended_at is not None:
                raise RuntimeError(f"trace {self.id} is already closed")
            self.tool_calls.append(call)

    def record_event(
        self,
        event_type: str,
        *,
        call_id: str | None = None,
        tool_name: str | None = None,
        arguments: dict[str, Any] | None = None,
        response: Any = None,
        duration_ms: int | None = None,
    ) -> RecordedEvent:
        """Append one event, claiming the next sequence number.

        Snapshotting happens before the lock is taken: it is the slow part, and
        holding the counter while serialising an arbitrary payload would make
        every concurrent tool wait on the widest one.
        """
        recorded_arguments = snapshot_object(arguments)
        recorded_response = snapshot(response)
        with self._lock:
            if self.ended_at is not None:
                raise RuntimeError(f"trace {self.id} is already closed")
            event = RecordedEvent(
                sequence=self._sequence,
                event_type=event_type,
                call_id=call_id,
                tool_name=tool_name,
                arguments=recorded_arguments,
                response=recorded_response,
                duration_ms=duration_ms,
            )
            self._sequence += 1
            self.events.append(event)
        return event

    def set_output(self, value: Any) -> None:
        """Record what the agent produced, wrapped into a JSON object."""
        self.output = snapshot_object(value)

    def close(self) -> None:
        """Mark the trace finished.

        Takes the same lock as the appenders, so a tool recording from another
        thread cannot slip an event in after the run has been closed and
        uploaded.
        """
        with self._lock:
            if self.ended_at is not None:
                raise RuntimeError(f"trace {self.id} is already closed")
            self.ended_at = _now()
