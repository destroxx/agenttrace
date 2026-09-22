"""The recording entrypoint used by instrumented agents."""

from __future__ import annotations

import asyncio
import functools
import inspect
import logging
import time
from collections import deque
from collections.abc import Callable
from contextvars import ContextVar, Token
from types import TracebackType
from typing import Any

from agenttrace import replay as _replay
from agenttrace import transport
from agenttrace.config import TracerConfig
from agenttrace.errors import ReplayedToolError, ReplayError
from agenttrace.models import RecordedEvent, ToolCall, Trace, snapshot_object
from agenttrace.recording import Recording

logger = logging.getLogger("agenttrace")

# A long-running server records a trace per request forever, so the history has
# to be bounded or the tracer becomes a memory leak that only shows up in
# production. Recent traces are what anyone actually inspects; older ones have
# already been uploaded.
COMPLETED_TRACE_LIMIT = 100

EVENT_AGENT_START = "agent_start"
EVENT_AGENT_END = "agent_end"
EVENT_TOOL_CALL = "tool_call"
EVENT_TOOL_RESPONSE = "tool_response"
EVENT_ERROR = "error"

STATUS_COMPLETED = "completed"
STATUS_FAILED = "failed"


def _error_payload(exc: BaseException) -> dict[str, str]:
    """Describe a failure in JSON, without dragging the exception along.

    A replayed error that could not be rebuilt as its own class is described
    under the name it was recorded with, so a replay's trace says the same
    thing its recording did rather than naming the SDK's stand-in.
    """
    if isinstance(exc, ReplayedToolError):
        return {"type": exc.error_type, "message": exc.message}
    return {"type": type(exc).__name__, "message": str(exc)}


def _bind_arguments(
    func: Callable[..., Any], args: tuple[Any, ...], kwargs: dict[str, Any]
) -> dict[str, Any]:
    """Name a call's arguments the way the function declares them.

    Positional arguments recorded as a list would be unreadable in a trace and
    useless to replay, which has to match a call by name. `self`/`cls` is
    dropped: the receiver is not an input, and it is rarely serialisable.
    """
    try:
        signature = inspect.signature(func)
        bound = signature.bind(*args, **kwargs)
        bound.apply_defaults()
        arguments = dict(bound.arguments)
        parameters = list(signature.parameters)
        if parameters and parameters[0] in ("self", "cls"):
            arguments.pop(parameters[0], None)
        return arguments
    except Exception:
        # A signature the inspect module cannot bind is not worth a failure.
        logger.warning("agenttrace: could not bind arguments", exc_info=True)
        return {}


class _TraceContext:
    """The object `tracer.trace(...)` returns.

    Implements both the sync and the async context manager protocol from one
    class so an agent can be written either way without a second entrypoint.
    The two differ in exactly one respect: how the end-of-run upload is waited
    for.
    """

    __slots__ = ("_token", "_trace", "_tracer")

    def __init__(self, tracer: AgentTracer, trace: Trace) -> None:
        self._tracer = tracer
        self._trace = trace
        self._token: Token[Trace | None] | None = None

    def _begin(self) -> Trace:
        self._token = self._tracer._activate(self._trace)
        session = _replay.current_session()
        if session is not None:
            # Adopted only once activation succeeded: a trace refused as
            # nested never ran, so it must not count as the replay's run.
            session.adopt(self._trace)
        self._tracer._record(self._trace, EVENT_AGENT_START)
        return self._trace

    def _finish(self, exc: BaseException | None) -> None:
        trace = self._trace
        if exc is None:
            self._tracer._record(trace, EVENT_AGENT_END)
            trace.status = STATUS_COMPLETED
        else:
            self._tracer._record(trace, EVENT_ERROR, response=_error_payload(exc))
            trace.status = STATUS_FAILED
        self._tracer._deactivate(self._token)
        self._token = None
        try:
            trace.close()
        except Exception:
            logger.warning("agenttrace: could not close trace %s", trace.id, exc_info=True)
        self._tracer._remember(trace)

    def __enter__(self) -> Trace:
        return self._begin()

    def __exit__(
        self,
        exc_type: type[BaseException] | None,
        exc: BaseException | None,
        tb: TracebackType | None,
    ) -> bool:
        self._finish(exc)
        self._tracer._upload(self._trace)
        # Never swallow: whatever the agent raised is the agent's business.
        return False

    async def __aenter__(self) -> Trace:
        return self._begin()

    async def __aexit__(
        self,
        exc_type: type[BaseException] | None,
        exc: BaseException | None,
        tb: TracebackType | None,
    ) -> bool:
        self._finish(exc)
        try:
            # The upload is blocking stdlib HTTP, so it goes to a worker thread
            # rather than stalling the event loop for the whole timeout.
            await asyncio.to_thread(self._tracer._upload, self._trace)
        except Exception:
            logger.warning(
                "agenttrace: could not upload trace %s", self._trace.id, exc_info=True
            )
        return False


class AgentTracer:
    """Records an agent execution and uploads it when the run ends.

    A whole run is buffered in memory and sent in one request, so the API
    stores the run and its events in a single transaction. The trade-off is
    deliberate and worth stating: a hard process kill loses the run in flight.

    Nothing here is allowed to change how the host application behaves. Tool
    results and exceptions pass through untouched, and any failure to record or
    upload is logged to the `agenttrace` logger and swallowed.

    Example:
        tracer = AgentTracer()

        @tracer.tool
        async def get_order(order_id: str) -> dict:
            ...

        async with tracer.trace("support-agent", input={"q": "where is it?"}):
            await get_order("A-1")
    """

    def __init__(self, config: TracerConfig | None = None) -> None:
        self._config = config or TracerConfig.from_env()
        # Per-instance rather than a module global, and a ContextVar rather
        # than an attribute: two agent runs on the same event loop each get
        # their own view of "the active trace", so their events cannot mix.
        self._active: ContextVar[Trace | None] = ContextVar(
            f"agenttrace_active_{id(self):x}", default=None
        )
        self._completed: deque[Trace] = deque(maxlen=COMPLETED_TRACE_LIMIT)

    @property
    def config(self) -> TracerConfig:
        """The configuration this tracer was built with."""
        return self._config

    @property
    def active_trace(self) -> Trace | None:
        """The trace currently being recorded in this context, if any."""
        return self._active.get()

    @property
    def completed_traces(self) -> tuple[Trace, ...]:
        """The most recent finished traces, oldest first.

        Capped at `COMPLETED_TRACE_LIMIT`; older traces are dropped.
        """
        return tuple(self._completed)

    def trace(
        self,
        name: str,
        *,
        input: Any = None,
        agent_version: str | None = None,
        **metadata: Any,
    ) -> _TraceContext:
        """Record everything inside the block as one run, then upload it.

        Usable as either `with` or `async with`. The trace is closed and sent
        even when the agent raises, so a failed run is still recorded; the
        original exception is re-raised untouched.
        """
        # Trace.__post_init__ snapshots and shapes `input` and `metadata`, so
        # they are handed over raw rather than coerced twice.
        current = Trace(
            name=name,
            metadata=metadata,
            input=input,
            agent_version=agent_version,
        )
        return _TraceContext(self, current)

    def record_tool_call(
        self,
        name: str,
        arguments: dict[str, Any] | None = None,
        response: Any = None,
    ) -> ToolCall:
        """Record one tool invocation against the active trace.

        Writes the call and its answer as two events sharing a `call_id`, which
        is what lets replay pair them when an agent calls several tools at once.
        """
        trace = self._active.get()
        if trace is None:
            raise RuntimeError("no active trace; call record_tool_call inside trace()")
        call = ToolCall(name=name, arguments=dict(arguments or {}), response=response)
        trace.add_tool_call(call)
        call_event = self._record(
            trace,
            EVENT_TOOL_CALL,
            call_id=call.id,
            tool_name=name,
            arguments=call.arguments,
        )
        response_event = self._record(
            trace,
            EVENT_TOOL_RESPONSE,
            call_id=call.id,
            tool_name=name,
            response=response,
        )
        # Adopt what was recorded, so the call and its events cannot disagree.
        if call_event is not None:
            call.arguments = call_event.arguments or {}
        if response_event is not None:
            call.response = response_event.response
        return call

    def tool(
        self, func: Callable[..., Any] | None = None, *, name: str | None = None
    ) -> Any:
        """Record a function as a tool. Usable bare or with a name.

        Works on sync and async functions alike. Outside a trace the wrapper
        does nothing but call through, so the same code runs instrumented or
        not, and a recording failure never costs the tool's real result.

        Inside `replay(...)` the real function is never called, trace or no
        trace: the call is answered from the recording instead.
        """

        def decorate(target: Callable[..., Any]) -> Callable[..., Any]:
            tool_name = name or target.__name__

            if inspect.iscoroutinefunction(target):

                @functools.wraps(target)
                async def async_wrapper(*args: Any, **kwargs: Any) -> Any:
                    trace = self._active.get()
                    session = _replay.current_session()
                    if session is not None:
                        return self._replay_tool(session, trace, tool_name, target, args, kwargs)
                    if trace is None:
                        return await target(*args, **kwargs)
                    arguments = _bind_arguments(target, args, kwargs)
                    call = self._begin_tool(trace, tool_name, arguments)
                    started = time.perf_counter()
                    try:
                        result = await target(*args, **kwargs)
                    except BaseException as exc:
                        # BaseException, not Exception, purely so a cancelled or
                        # interrupted tool does not leave a tool_call with no
                        # answer in the recording. The bare `raise` below is what
                        # keeps the "never swallow" rule: nothing is caught that
                        # is not immediately re-raised, so CancelledError and
                        # KeyboardInterrupt still propagate unchanged.
                        self._end_tool(trace, call, tool_name, started, error=exc)
                        raise
                    self._end_tool(trace, call, tool_name, started, response=result)
                    return result

                return async_wrapper

            @functools.wraps(target)
            def sync_wrapper(*args: Any, **kwargs: Any) -> Any:
                trace = self._active.get()
                session = _replay.current_session()
                if session is not None:
                    return self._replay_tool(session, trace, tool_name, target, args, kwargs)
                if trace is None:
                    return target(*args, **kwargs)
                arguments = _bind_arguments(target, args, kwargs)
                call = self._begin_tool(trace, tool_name, arguments)
                started = time.perf_counter()
                try:
                    result = target(*args, **kwargs)
                except BaseException as exc:
                    # See the async wrapper: caught only to record, re-raised
                    # immediately and unchanged.
                    self._end_tool(trace, call, tool_name, started, error=exc)
                    raise
                self._end_tool(trace, call, tool_name, started, response=result)
                return result

            return sync_wrapper

        if func is not None:
            return decorate(func)
        return decorate

    def _activate(self, trace: Trace) -> Token[Trace | None]:
        """Make `trace` the active one, refusing to nest."""
        existing = self._active.get()
        if existing is not None:
            raise RuntimeError(
                f"trace {existing.id!r} is already active; nested traces "
                "are not supported"
            )
        return self._active.set(trace)

    def _deactivate(self, token: Token[Trace | None] | None) -> None:
        try:
            if token is not None:
                self._active.reset(token)
            else:
                self._active.set(None)
        except Exception:
            # Resetting a token from a different context raises; clearing the
            # variable is the safe fallback and matters more than the token.
            logger.debug("agenttrace: could not reset trace token", exc_info=True)
            self._active.set(None)

    def _remember(self, trace: Trace) -> None:
        self._completed.append(trace)

    def _record(
        self, trace: Trace, event_type: str, **fields: Any
    ) -> RecordedEvent | None:
        """Record an event, treating any failure as a lost event, not an error.

        Returns the stored event so a caller can adopt the snapshot it took,
        rather than snapshotting the same value a second time.
        """
        try:
            return trace.record_event(event_type, **fields)
        except Exception:
            logger.warning(
                "agenttrace: could not record %s on trace %s",
                event_type,
                trace.id,
                exc_info=True,
            )
            return None

    def _begin_tool(
        self, trace: Trace, tool_name: str, arguments: dict[str, Any]
    ) -> ToolCall | None:
        """Open a decorated tool call. Returns None if recording failed."""
        try:
            call = ToolCall(name=tool_name, arguments=arguments)
            trace.add_tool_call(call)
        except Exception:
            logger.warning(
                "agenttrace: could not record call to %s", tool_name, exc_info=True
            )
            return None
        event = self._record(
            trace,
            EVENT_TOOL_CALL,
            call_id=call.id,
            tool_name=tool_name,
            arguments=call.arguments,
        )
        if event is not None:
            call.arguments = event.arguments or {}
        return call

    def _end_tool(
        self,
        trace: Trace,
        call: ToolCall | None,
        tool_name: str,
        started: float,
        *,
        response: Any = None,
        error: BaseException | None = None,
    ) -> None:
        """Close a decorated tool call with its answer or its failure."""
        duration_ms = max(0, int((time.perf_counter() - started) * 1000))
        try:
            if call is not None:
                call.duration_ms = duration_ms
                if error is not None:
                    call.error = f"{type(error).__name__}: {error}"
        except Exception:
            logger.warning("agenttrace: could not finish call record", exc_info=True)

        call_id = call.id if call is not None else None
        if error is None:
            event = self._record(
                trace,
                EVENT_TOOL_RESPONSE,
                call_id=call_id,
                tool_name=tool_name,
                response=response,
                duration_ms=duration_ms,
            )
            if call is not None and event is not None:
                call.response = event.response
        else:
            self._record(
                trace,
                EVENT_ERROR,
                call_id=call_id,
                tool_name=tool_name,
                response=_error_payload(error),
                duration_ms=duration_ms,
            )

    def _replay_tool(
        self,
        session: _replay.ReplaySession,
        trace: Trace | None,
        tool_name: str,
        target: Callable[..., Any],
        args: tuple[Any, ...],
        kwargs: dict[str, Any],
    ) -> Any:
        """Answer a decorated tool call from the recording. `target` never runs.

        The call is recorded into the replay's own trace exactly as a live one
        would be -- a `tool_call`, then a `tool_response` or `error` sharing its
        `call_id` -- so the replay is itself an ordinary, comparable trace.
        Unlike recording, this raises into the agent on purpose: a recorded
        failure is re-raised, and a call the recording cannot answer raises
        `UnmatchedToolCall` rather than falling through to the real tool.
        """
        arguments = _bind_arguments(target, args, kwargs)
        live_arguments = snapshot_object(arguments) or {}
        call = self._begin_tool(trace, tool_name, arguments) if trace is not None else None
        started = time.perf_counter()
        recorded = session.resolve(tool_name, live_arguments, call.id if call else None)
        try:
            result = _replay.recorded_outcome(tool_name, live_arguments, recorded)
        except Exception as exc:
            if trace is not None:
                self._end_tool(trace, call, tool_name, started, error=exc)
            raise
        if trace is not None:
            self._end_tool(trace, call, tool_name, started, response=result)
        return result

    async def replay(
        self,
        recording: Recording,
        agent_fn: Callable[[dict[str, Any]], Any],
        *,
        agent_version: str | None = None,
    ) -> _replay.ReplayResult:
        """Run `agent_fn` again with every decorated tool answered from `recording`.

        `agent_fn` is the agent's ordinary entry point -- the same one that
        records in production -- and is called with `recording.input`. It must
        open its own `tracer.trace(...)`; that trace is marked as a replay of
        the recording and uploads as usual. `agent_version`, if given,
        overrides the version on that trace.

        A synchronous `agent_fn` runs in `asyncio.to_thread`, which carries the
        replay session into the worker. An exception from the agent is
        captured into the result rather than raised, because a replay that
        fails is still a result worth inspecting; `BaseException` propagates.
        Raises `ReplayError` when called inside another replay.
        """
        if _replay.current_session() is not None:
            raise ReplayError("replay sessions cannot be nested")
        session = _replay.ReplaySession(recording=recording, agent_version=agent_version)
        token = _replay.activate(session)
        return_value: Any = None
        error: dict[str, str] | None = None
        try:
            if inspect.iscoroutinefunction(agent_fn):
                return_value = await agent_fn(recording.input)
            else:
                return_value = await asyncio.to_thread(agent_fn, recording.input)
            # A sync wrapper around an async entry point hands back a coroutine.
            if inspect.isawaitable(return_value):
                return_value = await return_value
        except Exception as exc:  # noqa: BLE001 - the agent's failure is the result
            # The exception's own class, even for a ReplayedToolError: the
            # result reports what reached the caller, the trace what was recorded.
            error = {"type": type(exc).__name__, "message": str(exc)}
        finally:
            _replay.deactivate(token)
        return session.result(return_value, error)

    def _upload(self, trace: Trace) -> None:
        """Send a finished trace, if there is anywhere to send it."""
        if not self._config.upload_enabled:
            return
        try:
            trace.uploaded = transport.upload(trace, self._config)
        except Exception:
            logger.warning(
                "agenttrace: could not upload trace %s", trace.id, exc_info=True
            )
            trace.uploaded = False

    def __repr__(self) -> str:
        active = self._active.get()
        return (
            f"AgentTracer(config={self._config!r}, "
            f"active={active.id if active else None!r}, "
            f"completed={len(self._completed)})"
        )
