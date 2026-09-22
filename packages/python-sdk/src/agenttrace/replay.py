"""Replay sessions and their results.

A replay runs the customer's own agent entry point again, unchanged, while
every `@tracer.tool` call is answered from a recording instead of executing.
This module holds the session that does the bookkeeping -- which recorded
calls have been handed out, and how each live call matched -- and the
result it produces. `AgentTracer.replay` is the entry point; the tool
decorator consults `current_session()`.
"""

from __future__ import annotations

import ast
import builtins
import copy
import logging
import threading
from contextvars import ContextVar
from dataclasses import dataclass, field
from typing import Any

from agenttrace.errors import ReplayedToolError, ReplayError, UnmatchedToolCall
from agenttrace.matching import (
    TIER_EXACT,
    TIER_NORMALIZED,
    TIER_UNMATCHED,
    Fingerprint,
    find_match,
    fingerprint,
)
from agenttrace.models import Trace
from agenttrace.recording import OUTCOME_ERROR, OUTCOME_RESPONSE, RecordedToolCall, Recording

logger = logging.getLogger("agenttrace")

STATUS_COMPLETED = "completed"
STATUS_FAILED = "failed"

# Module-level, not per tracer. A replay must never let a real tool run, and
# an agent's tools are often decorated by a different `AgentTracer` instance
# than the one `replay` was called on -- a per-tracer variable would leave
# those tools live. The trace is per tracer because two tracers recording at
# once is legitimate; two replays at once in one context is not.
_SESSION: ContextVar[ReplaySession | None] = ContextVar("agenttrace_replay", default=None)


def current_session() -> ReplaySession | None:
    """The replay session active in this context, if any."""
    return _SESSION.get()


@dataclass(frozen=True, slots=True)
class ToolCallMatch:
    """How one live tool call lined up against the recording.

    `new_call_id` is None when the call was made outside any trace, so it was
    replayed but not recorded. `recorded_*` are None when nothing matched.
    """

    tool_name: str
    tier: str
    new_call_id: str | None
    new_arguments: dict[str, Any]
    recorded_call_id: str | None = None
    recorded_arguments: dict[str, Any] | None = None
    recorded_sequence: int | None = None


@dataclass(frozen=True, slots=True)
class UnusedRecordedCall:
    """A recorded call no live call matched: the new agent skipped a step."""

    tool_name: str
    recorded_call_id: str | None
    arguments: dict[str, Any]
    recorded_sequence: int


@dataclass(frozen=True, slots=True)
class ReplaySummary:
    """Counts over one replay. Facts only; deciding pass or fail is not replay's job."""

    recorded_calls: int
    replayed_calls: int
    exact: int
    normalized: int
    unmatched: int
    unused: int


@dataclass(slots=True)
class ReplayResult:
    """Everything that happened in one replay.

    `trace` is the run the replay recorded -- a normal trace, uploaded like
    any other when upload is enabled. `output` is that trace's output, so it
    can be compared with `Recording.output`; `return_value` is what the entry
    point itself returned. `error` is `{"type", "message"}` when the agent
    raised, or when it did not open exactly one trace.
    """

    recording_run_id: str
    trace: Trace | None
    status: str
    output: dict[str, Any] | None
    return_value: Any
    error: dict[str, str] | None
    matches: list[ToolCallMatch]
    unused: list[UnusedRecordedCall]
    summary: ReplaySummary
    # Every trace the agent opened; more than one is reported in `error`.
    traces: tuple[Trace, ...] = ()


@dataclass(slots=True)
class ReplaySession:
    """The mutable state of one replay, shared by every task and thread in it.

    Tools may run concurrently -- `asyncio.gather`, or sync tools in worker
    threads -- so matching a call and consuming its recorded answer happen
    together under one lock; otherwise two identical calls could both claim
    the same recorded answer.
    """

    recording: Recording
    agent_version: str | None = None
    consumed: set[int] = field(default_factory=set)
    matches: list[ToolCallMatch] = field(default_factory=list)
    traces: list[Trace] = field(default_factory=list)
    _fingerprints: tuple[Fingerprint, ...] = ()
    _lock: threading.Lock = field(default_factory=threading.Lock, repr=False)

    def __post_init__(self) -> None:
        # Fingerprinted once up front: each live call is compared against
        # every recorded one, and re-serialising them per call would be
        # quadratic in JSON work.
        self._fingerprints = tuple(
            fingerprint(call.tool_name, call.arguments) for call in self.recording.tool_calls
        )

    def adopt(self, trace: Trace) -> None:
        """Mark a trace opened inside this replay as a replay of the recording."""
        trace.replay_of_run_id = self.recording.run_id
        if self.agent_version is not None:
            trace.agent_version = self.agent_version
        with self._lock:
            self.traces.append(trace)

    def resolve(
        self, tool_name: str, arguments: dict[str, Any], new_call_id: str | None
    ) -> RecordedToolCall | None:
        """Match a live call, consume the recorded call it matched, and log it."""
        live = fingerprint(tool_name, arguments)
        with self._lock:
            found = find_match(live, self._fingerprints, self.consumed)
            if found is None:
                self.matches.append(
                    ToolCallMatch(
                        tool_name=tool_name,
                        tier=TIER_UNMATCHED,
                        new_call_id=new_call_id,
                        new_arguments=arguments,
                    )
                )
                return None
            index, tier = found
            self.consumed.add(index)
            recorded = self.recording.tool_calls[index]
            self.matches.append(
                ToolCallMatch(
                    tool_name=tool_name,
                    tier=tier,
                    new_call_id=new_call_id,
                    new_arguments=arguments,
                    recorded_call_id=recorded.call_id,
                    recorded_arguments=recorded.arguments,
                    recorded_sequence=recorded.sequence,
                )
            )
            return recorded

    def result(self, return_value: Any, error: dict[str, str] | None) -> ReplayResult:
        """Freeze the session into a result once the agent has finished."""
        with self._lock:
            matches = list(self.matches)
            traces = tuple(self.traces)
            consumed = set(self.consumed)
        unused = [
            UnusedRecordedCall(
                tool_name=call.tool_name,
                recorded_call_id=call.call_id,
                arguments=call.arguments,
                recorded_sequence=call.sequence,
            )
            for index, call in enumerate(self.recording.tool_calls)
            if index not in consumed
        ]
        if error is None and len(traces) != 1:
            error = {
                "type": ReplayError.__name__,
                "message": (
                    "the agent opened no trace; replay needs the entry point to open "
                    "tracer.trace(...)"
                    if not traces
                    else f"the agent opened {len(traces)} traces; replay expects exactly one"
                ),
            }
        trace = traces[0] if traces else None
        if error is None and trace is not None:
            status = trace.status
        else:
            status = STATUS_FAILED
        tiers = [match.tier for match in matches]
        return ReplayResult(
            recording_run_id=self.recording.run_id,
            trace=trace,
            status=status,
            output=trace.output if trace is not None else None,
            return_value=return_value,
            error=error,
            matches=matches,
            unused=unused,
            summary=ReplaySummary(
                recorded_calls=len(self.recording.tool_calls),
                replayed_calls=len(matches),
                exact=tiers.count(TIER_EXACT),
                normalized=tiers.count(TIER_NORMALIZED),
                unmatched=tiers.count(TIER_UNMATCHED),
                unused=len(unused),
            ),
            traces=traces,
        )


def activate(session: ReplaySession) -> Any:
    """Make `session` current; returns the token `deactivate` needs."""
    return _SESSION.set(session)


def deactivate(token: Any) -> None:
    _SESSION.reset(token)


def recorded_outcome(tool_name: str, arguments: dict[str, Any], recorded: RecordedToolCall | None) -> Any:
    """Turn a match into what the tool call returns, or raise what it raised.

    The response is deep-copied so an agent that edits a replayed value in
    place cannot change the recording -- the next identical call, or the
    comparison afterwards, must still see what was recorded.
    """
    if recorded is None:
        raise UnmatchedToolCall(tool_name, arguments)
    if recorded.outcome == OUTCOME_RESPONSE:
        return copy.deepcopy(recorded.response)
    if recorded.outcome == OUTCOME_ERROR:
        error = recorded.error or {}
        raise rebuild_exception(str(error.get("type", "Error")), str(error.get("message", "")))
    raise ReplayedToolError(
        "NoRecordedResult",
        f"the recorded call to {tool_name!r} (call_id {recorded.call_id!r}) has no "
        "recorded response or error",
    )


def rebuild_exception(error_type: str, message: str) -> Exception:
    """Recreate a recorded failure as closely as the recording allows.

    Only a builtin `Exception` subclass is rebuilt as itself: the recording
    holds a bare type name, and resolving any other name would mean importing
    whatever the recording says, from wherever. `BaseException`-only types
    (`KeyboardInterrupt`, `SystemExit`) are never rebuilt -- replay must not
    stop the test process because a recorded run was interrupted. A builtin
    whose constructor needs more than a message falls back as well.
    """
    candidate = getattr(builtins, error_type, None)
    if isinstance(candidate, type) and issubclass(candidate, Exception):
        argument: Any = message
        if issubclass(candidate, KeyError):
            # str(KeyError(k)) is repr(k), so the recorded message is already
            # quoted; rebuilding from it verbatim would quote it twice.
            try:
                argument = ast.literal_eval(message)
            except (ValueError, SyntaxError):
                argument = message
        try:
            return candidate(argument)
        except Exception:  # noqa: BLE001 - e.g. UnicodeDecodeError takes five arguments
            logger.debug("agenttrace: could not rebuild %s; raising it wrapped", error_type)
    return ReplayedToolError(error_type, message)
