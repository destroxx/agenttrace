"""The recording entrypoint used by instrumented agents."""

from __future__ import annotations

from collections.abc import Iterator
from contextlib import contextmanager
from typing import Any

from agenttrace.config import TracerConfig
from agenttrace.models import ToolCall, Trace


class AgentTracer:
    """Records an agent execution.

    Traces are held in memory for this milestone. Uploading them to the
    AgentTrace API, and replaying them, are separate milestones; the public
    surface below is intended to stay stable across that change.

    Example:
        tracer = AgentTracer()
        with tracer.trace("checkout-agent") as trace:
            tracer.record_tool_call("search", {"q": "shoes"}, response=[...])
    """

    def __init__(self, config: TracerConfig | None = None) -> None:
        self._config = config or TracerConfig.from_env()
        self._active: Trace | None = None
        self._completed: list[Trace] = []

    @property
    def config(self) -> TracerConfig:
        """The configuration this tracer was built with."""
        return self._config

    @property
    def active_trace(self) -> Trace | None:
        """The trace currently being recorded, if any."""
        return self._active

    @property
    def completed_traces(self) -> tuple[Trace, ...]:
        """Traces recorded so far, oldest first."""
        return tuple(self._completed)

    @contextmanager
    def trace(self, name: str, **metadata: Any) -> Iterator[Trace]:
        """Record everything captured inside the block as one trace.

        The trace is closed even if the agent raises, so a failed run is still
        recorded.
        """
        if self._active is not None:
            raise RuntimeError(
                f"trace {self._active.id!r} is already active; nested traces "
                "are not supported"
            )
        current = Trace(name=name, metadata=dict(metadata))
        self._active = current
        try:
            yield current
        finally:
            self._active = None
            current.close()
            self._completed.append(current)

    def record_tool_call(
        self,
        name: str,
        arguments: dict[str, Any] | None = None,
        response: Any = None,
    ) -> ToolCall:
        """Record one tool invocation against the active trace."""
        if self._active is None:
            raise RuntimeError("no active trace; call record_tool_call inside trace()")
        call = ToolCall(name=name, arguments=dict(arguments or {}), response=response)
        self._active.add_tool_call(call)
        return call

    def __repr__(self) -> str:
        return (
            f"AgentTracer(config={self._config!r}, "
            f"active={self._active.id if self._active else None!r}, "
            f"completed={len(self._completed)})"
        )
