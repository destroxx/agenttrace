"""A recorded run, loaded for replay.

A `Recording` is the fixture a replay runs against: the run's input and
outcome, and every tool call it made paired with the answer that call got.
It can be built from an in-memory `Trace`, from the ingest payload the SDK
uploads, or fetched from the API -- all three go through the same
`from_payload`, so there is one reading of a trace, not three.

Unlike recording, loading a recording raises: it is only ever done on purpose,
by a developer or a test, and a silently empty fixture would make every
replay against it look like a regression.
"""

from __future__ import annotations

import asyncio
import json
import urllib.error
import urllib.request
from collections.abc import Mapping
from dataclasses import dataclass
from typing import Any

from agenttrace.config import TracerConfig
from agenttrace.errors import AgentTraceAPIError, RecordingNotFound, ReplayError
from agenttrace.models import Trace
from agenttrace.transport import build_payload

RUN_PATH = "/api/v1/runs/{run_id}"
EVENTS_PATH = "/api/v1/runs/{run_id}/events"

# How a recorded call ended. "no_result" is a call whose answer never made it
# into the recording -- the process died mid-call, or the recorder lost the
# event -- and is kept rather than dropped, so replay can say so.
OUTCOME_RESPONSE = "response"
OUTCOME_ERROR = "error"
OUTCOME_NO_RESULT = "no_result"

_TOOL_CALL = "tool_call"
_TOOL_RESPONSE = "tool_response"
_ERROR = "error"
_NOT_FOUND = 404


@dataclass(frozen=True, slots=True)
class RecordedToolCall:
    """One tool call from a recording, with the answer it got.

    `sequence` is the position of the `tool_call` event, which is the order
    replay hands recorded answers out in. `error` is the recorded
    `{"type": ..., "message": ...}` when the tool raised. The payload dicts are
    shared with the recording and must be treated as read-only; replay hands
    the agent a copy of `response`, never this object.
    """

    sequence: int
    call_id: str | None
    tool_name: str
    arguments: dict[str, Any]
    outcome: str
    response: Any = None
    error: dict[str, Any] | None = None


@dataclass(frozen=True, slots=True)
class Recording:
    """An immutable recorded run: what the agent was given, and what its tools said."""

    run_id: str
    agent_name: str
    agent_version: str | None
    input: dict[str, Any]
    output: dict[str, Any] | None
    status: str
    tool_calls: tuple[RecordedToolCall, ...]
    # Known only for a recording fetched from the API.
    project_id: str | None = None

    @classmethod
    def from_payload(cls, payload: Mapping[str, Any]) -> Recording:
        """Build from a `RunIngest`-shaped dict, such as `build_payload(trace)`.

        Events are read in `sequence` order whatever order they arrive in.
        Each `tool_call` is paired with the first `tool_response` or `error`
        that carries its `call_id` -- `sequence` alone cannot say which answer
        belongs to which of several parallel calls. A `tool_call` with no
        `call_id` cannot be paired and is kept as "no recorded result".
        """
        run_id = payload.get("id")
        if not run_id:
            raise ReplayError("recording payload has no run 'id'")
        events = sorted(payload.get("events") or [], key=lambda event: event["sequence"])

        results: dict[str, Mapping[str, Any]] = {}
        for event in events:
            call_id = event.get("call_id")
            if call_id is None or call_id in results:
                continue
            if event.get("event_type") in (_TOOL_RESPONSE, _ERROR):
                results[call_id] = event

        calls = []
        for event in events:
            if event.get("event_type") != _TOOL_CALL:
                continue
            call_id = event.get("call_id")
            result = results.get(call_id) if call_id is not None else None
            if result is None:
                outcome, response, error = OUTCOME_NO_RESULT, None, None
            elif result.get("event_type") == _TOOL_RESPONSE:
                outcome, response, error = OUTCOME_RESPONSE, result.get("response"), None
            else:
                outcome, response, error = OUTCOME_ERROR, None, _error_of(result)
            calls.append(
                RecordedToolCall(
                    sequence=event["sequence"],
                    call_id=call_id,
                    tool_name=event.get("tool_name") or "",
                    arguments=event.get("arguments") or {},
                    outcome=outcome,
                    response=response,
                    error=error,
                )
            )

        project_id = payload.get("project_id")
        return cls(
            run_id=str(run_id),
            agent_name=payload.get("agent_name") or "",
            agent_version=payload.get("agent_version"),
            input=payload.get("input") or {},
            output=payload.get("output"),
            status=payload.get("status") or "",
            tool_calls=tuple(calls),
            project_id=str(project_id) if project_id else None,
        )

    @classmethod
    def from_trace(cls, trace: Trace) -> Recording:
        """Build from an in-memory trace, for record-then-replay in one process."""
        return cls.from_payload(build_payload(trace))

    @classmethod
    def from_api_sync(cls, run_id: str, config: TracerConfig | None = None) -> Recording:
        """Fetch a stored run and its events from the API.

        Raises `RecordingNotFound` on a 404 and `AgentTraceAPIError` for any
        other failure. The events endpoint returns a run's whole trace
        unpaginated, so one request per resource is the full recording.
        """
        config = config or TracerConfig.from_env()
        run = _get_json(config, RUN_PATH.format(run_id=run_id))
        events = _get_json(config, EVENTS_PATH.format(run_id=run_id))
        if not isinstance(run, dict) or not isinstance(events, list):
            raise AgentTraceAPIError(f"unexpected response shape fetching run {run_id}")
        return cls.from_payload({**run, "events": events})

    @classmethod
    async def from_api(cls, run_id: str, config: TracerConfig | None = None) -> Recording:
        """`from_api_sync`, off the event loop: urllib blocks for the whole request."""
        return await asyncio.to_thread(cls.from_api_sync, run_id, config)


def _error_of(event: Mapping[str, Any]) -> dict[str, Any]:
    """The recorded `{"type", "message"}` of a failed call, tolerating other shapes.

    The SDK always records that shape, but a trace posted by another recorder
    may not; its raw response is kept as the message rather than lost.
    """
    response = event.get("response")
    if isinstance(response, dict) and "type" in response:
        return {"type": str(response["type"]), "message": str(response.get("message", ""))}
    return {"type": "Error", "message": "" if response is None else str(response)}


def _get_json(config: TracerConfig, path: str) -> Any:
    """GET one API resource, raising the replay exceptions on any failure."""
    url = f"{config.api_url}{path}"
    request = urllib.request.Request(url, method="GET", headers={"Accept": "application/json"})
    if config.api_key:
        request.add_header("Authorization", f"Bearer {config.api_key}")
    try:
        with urllib.request.urlopen(request, timeout=config.timeout_seconds) as response:
            body = response.read()
    except urllib.error.HTTPError as exc:
        if exc.code == _NOT_FOUND:
            raise RecordingNotFound(f"GET {url}: not found", status=exc.code) from exc
        raise AgentTraceAPIError(f"GET {url} failed with status {exc.code}", status=exc.code) from exc
    except Exception as exc:
        raise AgentTraceAPIError(f"GET {url} failed: {exc!r}") from exc
    try:
        return json.loads(body)
    except ValueError as exc:
        raise AgentTraceAPIError(f"GET {url} returned a body that is not JSON") from exc
