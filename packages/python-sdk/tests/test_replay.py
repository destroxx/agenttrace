"""Tests for replay: recorded answers served back to an unchanged agent."""

from __future__ import annotations

import asyncio
from typing import Any

import pytest
from fake_api import closed_port, fake_api

from agenttrace import (
    AgentTraceAPIError,
    AgentTracer,
    Recording,
    RecordingNotFound,
    ReplayedToolError,
    ReplayError,
    TracerConfig,
    UnmatchedToolCall,
)
from agenttrace.transport import build_payload

PROJECT_ID = "3f1d9c88-5b7a-4f2e-9f6c-1b2a3c4d5e6f"


class Counter:
    """Counts how often a real tool body actually ran."""

    def __init__(self) -> None:
        self.calls = 0


def _record(tracer: AgentTracer, agent_fn: Any, agent_input: dict) -> Recording:
    """Run an agent live once and load what it recorded."""
    if asyncio.iscoroutinefunction(agent_fn):
        asyncio.run(agent_fn(agent_input))
    else:
        agent_fn(agent_input)
    return Recording.from_trace(tracer.completed_traces[-1])


def _order_agent(tracer: AgentTracer, counter: Counter, *, skip_status: bool = False,
                 order_id: str = "A-1"):
    """A small async agent: two tools, the second optional."""

    @tracer.tool
    async def get_order(order_id: str) -> dict:
        counter.calls += 1
        return {"id": order_id, "status": "shipped"}

    @tracer.tool
    async def get_status(order_id: str) -> str:
        counter.calls += 1
        return "arriving tomorrow"

    async def run_agent(agent_input: dict) -> str:
        async with tracer.trace("order-agent", input=agent_input, agent_version="v1") as trace:
            order = await get_order(order_id)
            reply = order["status"]
            if not skip_status:
                reply += ", " + await get_status(order["id"])
            trace.set_output({"reply": reply})
        return reply

    return run_agent


def test_real_tools_never_execute_during_replay() -> None:
    tracer = AgentTracer(TracerConfig())
    counter = Counter()
    agent = _order_agent(tracer, counter)
    recording = _record(tracer, agent, {"q": "where is A-1?"})
    assert counter.calls == 2
    counter.calls = 0

    result = asyncio.run(tracer.replay(recording, agent))

    assert counter.calls == 0
    assert result.error is None
    assert result.status == "completed"
    assert result.output == recording.output == {"reply": "shipped, arriving tomorrow"}
    assert result.return_value == "shipped, arriving tomorrow"
    assert [m.tier for m in result.matches] == ["exact", "exact"]
    assert result.unused == []
    assert result.summary.exact == 2 and result.summary.unused == 0


def test_the_replay_run_is_itself_a_normal_trace() -> None:
    tracer = AgentTracer(TracerConfig())
    agent = _order_agent(tracer, Counter())
    recording = _record(tracer, agent, {"q": "x"})

    result = asyncio.run(tracer.replay(recording, agent))

    trace = result.trace
    assert trace is not None and trace.id != recording.run_id
    assert trace.replay_of_run_id == recording.run_id
    assert [e.event_type for e in trace.events] == [
        "agent_start",
        "tool_call",
        "tool_response",
        "tool_call",
        "tool_response",
        "agent_end",
    ]
    calls = [e for e in trace.events if e.event_type == "tool_call"]
    responses = [e for e in trace.events if e.event_type == "tool_response"]
    assert [c.call_id for c in calls] == [r.call_id for r in responses]
    assert [m.new_call_id for m in result.matches] == [c.call_id for c in calls]
    assert [m.recorded_call_id for m in result.matches] == [
        c.call_id for c in recording.tool_calls
    ]
    assert responses[0].response == {"id": "A-1", "status": "shipped"}


def test_agent_version_overrides_the_replay_trace() -> None:
    tracer = AgentTracer(TracerConfig())
    agent = _order_agent(tracer, Counter())
    recording = _record(tracer, agent, {})

    result = asyncio.run(tracer.replay(recording, agent, agent_version="v2-candidate"))

    assert result.trace is not None and result.trace.agent_version == "v2-candidate"
    assert recording.agent_version == "v1"


def test_parallel_calls_get_their_own_recorded_responses() -> None:
    """Recorded answers arrived in reverse order; call_id pairing must hold."""
    tracer = AgentTracer(TracerConfig())
    counter = Counter()
    delays = {"A": 0.06, "B": 0.03, "C": 0.0}

    @tracer.tool
    async def lookup(key: str) -> str:
        counter.calls += 1
        await asyncio.sleep(delays[key])
        return f"value-{key}"

    async def agent(agent_input: dict) -> list:
        async with tracer.trace("parallel", input=agent_input) as trace:
            values = await asyncio.gather(*(lookup(k) for k in agent_input["keys"]))
            trace.set_output({"values": values})
        return values

    recording = _record(tracer, agent, {"keys": ["A", "B", "C"]})
    events = build_payload(tracer.completed_traces[-1])["events"]
    answered = [e["response"] for e in events if e["event_type"] == "tool_response"]
    assert answered == ["value-C", "value-B", "value-A"]  # completion order differs
    counter.calls = 0

    result = asyncio.run(tracer.replay(recording, agent))

    assert counter.calls == 0
    assert result.return_value == ["value-A", "value-B", "value-C"]
    assert result.summary.exact == 3


def test_identical_repeated_calls_get_the_recorded_answers_in_order() -> None:
    tracer = AgentTracer(TracerConfig())
    states = iter(["queued", "running", "done"])
    counter = Counter()

    @tracer.tool
    def poll(job_id: str) -> str:
        counter.calls += 1
        return next(states)

    def agent(agent_input: dict) -> list:
        with tracer.trace("poller") as trace:
            seen = [poll("job-1") for _ in range(3)]
            trace.set_output({"seen": seen})
        return seen

    recording = _record(tracer, agent, {})
    counter.calls = 0

    result = asyncio.run(tracer.replay(recording, agent))

    assert result.return_value == ["queued", "running", "done"]
    assert counter.calls == 0
    assert [m.recorded_sequence for m in result.matches] == sorted(
        m.recorded_sequence for m in result.matches
    )


class InventoryDown(Exception):
    """A user-defined exception: not a builtin, so it cannot be rebuilt."""


def test_recorded_errors_are_reraised() -> None:
    tracer = AgentTracer(TracerConfig())

    @tracer.tool
    async def slow() -> None:
        raise TimeoutError("upstream took too long")

    @tracer.tool
    async def missing(key: str) -> None:
        raise KeyError(key)

    @tracer.tool
    async def inventory() -> None:
        raise InventoryDown("warehouse offline")

    async def agent(agent_input: dict) -> list:
        caught: list = []
        async with tracer.trace("errors"):
            for tool in (slow, lambda: missing("sku-1"), inventory):
                try:
                    await tool()
                except Exception as exc:  # noqa: BLE001 - collecting what each raised
                    caught.append(exc)
        return caught

    recording = _record(tracer, agent, {})

    result = asyncio.run(tracer.replay(recording, agent))

    timeout, key_error, custom = result.return_value
    assert type(timeout) is TimeoutError
    assert str(timeout) == "upstream took too long"
    assert type(key_error) is KeyError
    assert str(key_error) == "'sku-1'"  # rebuilt, not quoted twice
    assert isinstance(custom, ReplayedToolError)
    assert custom.error_type == "InventoryDown"
    assert custom.message == "warehouse offline"
    # and the replay trace records them as errors, like a live run would
    errors = [e for e in result.trace.events if e.event_type == "error" and e.call_id]
    # under the recorded names, so the replay says what the recording said
    recorded = [c.error for c in recording.tool_calls]
    assert [e.response for e in errors] == recorded
    assert [e["type"] for e in recorded] == ["TimeoutError", "KeyError", "InventoryDown"]


def test_an_unmatched_call_raises_inside_the_agent_and_is_reported() -> None:
    tracer = AgentTracer(TracerConfig())
    counter = Counter()
    recording = _record(tracer, _order_agent(tracer, counter), {})
    counter.calls = 0
    changed = _order_agent(tracer, counter, order_id="Z-9")

    result = asyncio.run(tracer.replay(recording, changed))

    assert counter.calls == 0
    assert result.error is not None and result.error["type"] == "UnmatchedToolCall"
    assert result.status == "failed"
    [match] = result.matches
    assert match.tier == "unmatched"
    assert match.tool_name == "get_order"
    assert match.new_arguments == {"order_id": "Z-9"}
    assert match.recorded_call_id is None
    # the agent never got to get_status, and get_order A-1 was never claimed
    assert [u.tool_name for u in result.unused] == ["get_order", "get_status"]


def test_unmatched_tool_call_carries_name_and_arguments() -> None:
    tracer = AgentTracer(TracerConfig())

    @tracer.tool
    def lookup(key: str) -> str:
        return key

    def recorded_agent(agent_input: dict) -> None:
        with tracer.trace("a"):
            lookup("x")

    def new_agent(agent_input: dict) -> Any:
        with tracer.trace("a"):
            try:
                lookup("y")
            except UnmatchedToolCall as exc:
                return exc

    recording = _record(tracer, recorded_agent, {})
    result = asyncio.run(tracer.replay(recording, new_agent))

    exc = result.return_value
    assert isinstance(exc, UnmatchedToolCall)
    assert exc.tool_name == "lookup" and exc.arguments == {"key": "y"}
    assert result.error is None  # the agent handled it


def test_a_skipped_step_is_reported_as_unused() -> None:
    tracer = AgentTracer(TracerConfig())
    counter = Counter()
    recording = _record(tracer, _order_agent(tracer, counter), {})

    result = asyncio.run(tracer.replay(recording, _order_agent(tracer, counter, skip_status=True)))

    assert result.error is None
    assert [m.tool_name for m in result.matches] == ["get_order"]
    [unused] = result.unused
    assert unused.tool_name == "get_status"
    assert unused.arguments == {"order_id": "A-1"}
    assert unused.recorded_call_id == recording.tool_calls[1].call_id
    assert result.summary.unused == 1


def test_a_sync_agent_with_sync_tools_replays() -> None:
    tracer = AgentTracer(TracerConfig())
    counter = Counter()

    @tracer.tool
    def add(left: int, right: int) -> int:
        counter.calls += 1
        return left + right

    def agent(agent_input: dict) -> int:
        with tracer.trace("calc", input=agent_input) as trace:
            total = add(agent_input["a"], agent_input["b"])
            total = add(total, 1)
            trace.set_output({"total": total})
        return total

    recording = _record(tracer, agent, {"a": 2, "b": 3})
    counter.calls = 0

    result = asyncio.run(tracer.replay(recording, agent))

    assert counter.calls == 0
    assert result.return_value == 6
    assert result.output == {"total": 6}
    assert result.summary.exact == 2


def test_normalized_arguments_still_replay() -> None:
    tracer = AgentTracer(TracerConfig())

    @tracer.tool
    def search(q: str, limit: float = 10) -> list:
        return [q]

    def recorded(agent_input: dict) -> None:
        with tracer.trace("s"):
            search("shoes", 10)

    def drifted(agent_input: dict) -> list:
        with tracer.trace("s"):
            return search("  shoes ", 10.0)

    recording = _record(tracer, recorded, {})
    result = asyncio.run(tracer.replay(recording, drifted))

    assert result.return_value == ["shoes"]
    [match] = result.matches
    assert match.tier == "normalized"
    assert match.recorded_arguments == {"q": "shoes", "limit": 10}
    assert match.new_arguments == {"q": "  shoes ", "limit": 10.0}


def test_mutating_a_replayed_response_does_not_change_the_recording() -> None:
    tracer = AgentTracer(TracerConfig())

    @tracer.tool
    def fetch() -> dict:
        return {"items": [1]}

    def agent(agent_input: dict) -> list:
        with tracer.trace("m"):
            first = fetch()
            first["items"].append(99)
            return fetch()["items"]

    recording = _record(tracer, agent, {})
    result = asyncio.run(tracer.replay(recording, agent))

    assert result.return_value == [1]
    assert recording.tool_calls[0].response == {"items": [1]}


def test_tools_of_another_tracer_are_replayed_too() -> None:
    """Replay must never run a real tool, whichever tracer decorated it."""
    tools_tracer = AgentTracer(TracerConfig())
    counter = Counter()

    @tools_tracer.tool
    def lookup(key: str) -> str:
        counter.calls += 1
        return "live"

    def agent(agent_input: dict) -> str:
        with tools_tracer.trace("a"):
            return lookup("k")

    recording = _record(tools_tracer, agent, {})
    counter.calls = 0

    result = asyncio.run(AgentTracer(TracerConfig()).replay(recording, agent))

    assert counter.calls == 0
    assert result.return_value == "live"


def test_a_tool_called_outside_the_trace_is_replayed_not_run() -> None:
    tracer = AgentTracer(TracerConfig())
    counter = Counter()

    @tracer.tool
    def lookup(key: str) -> str:
        counter.calls += 1
        return "v"

    def recorded(agent_input: dict) -> None:
        with tracer.trace("a"):
            lookup("k")

    def new_agent(agent_input: dict) -> str:
        value = lookup("k")  # before the trace opens
        with tracer.trace("a"):
            pass
        return value

    recording = _record(tracer, recorded, {})
    counter.calls = 0
    result = asyncio.run(tracer.replay(recording, new_agent))

    assert counter.calls == 0
    assert result.return_value == "v"
    [match] = result.matches
    assert match.tier == "exact" and match.new_call_id is None


def test_record_tool_call_during_replay_is_recorded_but_not_replayed() -> None:
    tracer = AgentTracer(TracerConfig())

    def agent(agent_input: dict) -> None:
        with tracer.trace("manual"):
            tracer.record_tool_call("external", {"id": 1}, response="done")

    recording = _record(tracer, agent, {})
    result = asyncio.run(tracer.replay(recording, agent))

    assert result.matches == []
    assert [u.tool_name for u in result.unused] == ["external"]
    kinds = [e.event_type for e in result.trace.events]
    assert kinds == ["agent_start", "tool_call", "tool_response", "agent_end"]


def test_an_agent_exception_is_captured_in_the_result() -> None:
    tracer = AgentTracer(TracerConfig())
    agent = _order_agent(tracer, Counter())
    recording = _record(tracer, agent, {})

    async def broken(agent_input: dict) -> None:
        async with tracer.trace("order-agent"):
            raise ValueError("bad prompt")

    result = asyncio.run(tracer.replay(recording, broken))

    assert result.error == {"type": "ValueError", "message": "bad prompt"}
    assert result.status == "failed"
    assert result.trace is not None and result.trace.status == "failed"
    assert len(result.unused) == 2


def test_base_exceptions_propagate_out_of_replay() -> None:
    tracer = AgentTracer(TracerConfig())
    recording = _record(tracer, _order_agent(tracer, Counter()), {})

    async def interrupted(agent_input: dict) -> None:
        raise KeyboardInterrupt

    with pytest.raises(KeyboardInterrupt):
        asyncio.run(tracer.replay(recording, interrupted))


def test_nested_replay_raises() -> None:
    tracer = AgentTracer(TracerConfig())
    agent = _order_agent(tracer, Counter())
    recording = _record(tracer, agent, {})

    async def nesting(agent_input: dict) -> None:
        await tracer.replay(recording, agent)

    async def main():
        return await tracer.replay(recording, nesting)

    result = asyncio.run(main())
    assert result.error is not None
    assert result.error["type"] == "ReplayError"
    assert "nested" in result.error["message"]

    async def direct() -> None:
        from agenttrace import replay as replay_module

        token = replay_module.activate(replay_module.ReplaySession(recording=recording))
        try:
            with pytest.raises(ReplayError):
                await tracer.replay(recording, agent)
        finally:
            replay_module.deactivate(token)

    asyncio.run(direct())


def test_an_agent_that_opens_no_trace_is_reported() -> None:
    tracer = AgentTracer(TracerConfig())
    recording = _record(tracer, _order_agent(tracer, Counter()), {})

    result = asyncio.run(tracer.replay(recording, lambda agent_input: "no trace here"))

    assert result.trace is None
    assert result.status == "failed"
    assert result.error is not None and result.error["type"] == "ReplayError"
    assert "no trace" in result.error["message"]
    assert result.return_value == "no trace here"


def test_an_agent_that_opens_two_traces_is_reported() -> None:
    tracer = AgentTracer(TracerConfig())
    recording = _record(tracer, _order_agent(tracer, Counter()), {})

    def twice(agent_input: dict) -> None:
        for _ in range(2):
            with tracer.trace("again"):
                pass

    result = asyncio.run(tracer.replay(recording, twice))

    assert result.error is not None and "2 traces" in result.error["message"]
    assert len(result.traces) == 2


def test_recording_mode_is_unchanged_after_a_replay() -> None:
    tracer = AgentTracer(TracerConfig())
    counter = Counter()
    agent = _order_agent(tracer, counter)
    recording = _record(tracer, agent, {})
    asyncio.run(tracer.replay(recording, agent))
    counter.calls = 0

    asyncio.run(agent({}))

    assert counter.calls == 2
    assert tracer.completed_traces[-1].replay_of_run_id is None


# --- Recording ---------------------------------------------------------------


def _payload(events: list[dict]) -> dict:
    return {
        "id": "run-1",
        "agent_name": "a",
        "agent_version": None,
        "input": {"q": 1},
        "output": None,
        "status": "completed",
        "events": events,
    }


def test_from_payload_pairs_by_call_id_in_sequence_order() -> None:
    events = [
        {"sequence": 4, "event_type": "tool_response", "call_id": "b", "response": "B"},
        {"sequence": 1, "event_type": "tool_call", "call_id": "a", "tool_name": "t",
         "arguments": {"k": "a"}},
        {"sequence": 3, "event_type": "tool_response", "call_id": "a", "response": "A"},
        {"sequence": 2, "event_type": "tool_call", "call_id": "b", "tool_name": "t",
         "arguments": {"k": "b"}},
        {"sequence": 5, "event_type": "tool_call", "call_id": "c", "tool_name": "u",
         "arguments": {}},
        {"sequence": 6, "event_type": "error", "call_id": "c",
         "response": {"type": "ValueError", "message": "no"}},
        {"sequence": 7, "event_type": "tool_call", "call_id": "d", "tool_name": "v"},
    ]

    recording = Recording.from_payload(_payload(events))

    calls = recording.tool_calls
    assert [c.call_id for c in calls] == ["a", "b", "c", "d"]
    assert [c.response for c in calls[:2]] == ["A", "B"]
    assert calls[2].outcome == "error"
    assert calls[2].error == {"type": "ValueError", "message": "no"}
    assert calls[3].outcome == "no_result"
    assert recording.input == {"q": 1}


def test_a_call_with_no_recorded_result_raises_when_replayed() -> None:
    tracer = AgentTracer(TracerConfig())

    @tracer.tool
    def v() -> None:
        raise AssertionError("must not run")

    recording = Recording.from_payload(
        _payload([{"sequence": 1, "event_type": "tool_call", "call_id": "d", "tool_name": "v",
                   "arguments": {}}])
    )

    def agent(agent_input: dict) -> None:
        with tracer.trace("a"):
            v()

    result = asyncio.run(tracer.replay(recording, agent))

    assert result.error is not None
    assert result.error["type"] == "ReplayedToolError"
    assert result.matches[0].tier == "exact"


def test_from_payload_requires_a_run_id() -> None:
    with pytest.raises(ReplayError):
        Recording.from_payload({"events": []})


def _api_routes(run_id: str) -> dict:
    run = {
        "id": run_id,
        "project_id": PROJECT_ID,
        "agent_name": "order-agent",
        "agent_version": "v1",
        "input": {"q": "x"},
        "output": {"reply": "ok"},
        "metadata": None,
        "status": "completed",
        "started_at": "2026-09-18T10:00:00+00:00",
        "completed_at": "2026-09-18T10:00:01+00:00",
        "created_at": "2026-09-18T10:00:02+00:00",
        "replay_of_run_id": None,
    }
    events = [
        {"id": "e1", "run_id": run_id, "sequence": 0, "event_type": "agent_start",
         "call_id": None, "tool_name": None, "arguments": None, "response": None,
         "duration_ms": None, "created_at": "2026-09-18T10:00:02+00:00"},
        {"id": "e2", "run_id": run_id, "sequence": 1, "event_type": "tool_call",
         "call_id": "c1", "tool_name": "get_order", "arguments": {"order_id": "A-1"},
         "response": None, "duration_ms": None, "created_at": "2026-09-18T10:00:02+00:00"},
        {"id": "e3", "run_id": run_id, "sequence": 2, "event_type": "tool_response",
         "call_id": "c1", "tool_name": "get_order", "arguments": None,
         "response": {"status": "shipped"}, "duration_ms": 5,
         "created_at": "2026-09-18T10:00:02+00:00"},
    ]
    return {
        f"/api/v1/runs/{run_id}": (200, run),
        f"/api/v1/runs/{run_id}/events": (200, events),
    }


def test_from_api_fetches_the_run_and_its_events() -> None:
    run_id = "0b7c1a52-0000-4000-8000-000000000001"
    with fake_api() as api:
        api.routes.update(_api_routes(run_id))
        config = TracerConfig(api_url=api.url, project_id=PROJECT_ID)

        recording = asyncio.run(Recording.from_api(run_id, config))
        sync_recording = Recording.from_api_sync(run_id, config)

    assert recording == sync_recording
    assert recording.run_id == run_id
    assert recording.project_id == PROJECT_ID
    assert recording.input == {"q": "x"}
    assert recording.output == {"reply": "ok"}
    [call] = recording.tool_calls
    assert call.tool_name == "get_order"
    assert call.response == {"status": "shipped"}


def test_from_api_404_raises_recording_not_found() -> None:
    with fake_api() as api:
        config = TracerConfig(api_url=api.url)
        with pytest.raises(RecordingNotFound) as caught:
            Recording.from_api_sync("missing", config)
    assert caught.value.status == 404
    assert isinstance(caught.value, AgentTraceAPIError)


def test_from_api_500_raises_api_error() -> None:
    run_id = "0b7c1a52-0000-4000-8000-000000000002"
    with fake_api() as api:
        api.routes[f"/api/v1/runs/{run_id}"] = (500, {"detail": "boom"})
        config = TracerConfig(api_url=api.url)
        with pytest.raises(AgentTraceAPIError) as caught:
            asyncio.run(Recording.from_api(run_id, config))
    assert caught.value.status == 500
    assert not isinstance(caught.value, RecordingNotFound)


def test_from_api_with_the_api_down_raises_api_error() -> None:
    config = TracerConfig(api_url=f"http://127.0.0.1:{closed_port()}")
    with pytest.raises(AgentTraceAPIError) as caught:
        Recording.from_api_sync("any", config)
    assert caught.value.status is None


def test_the_replay_trace_uploads_with_replay_of_run_id() -> None:
    run_id = "0b7c1a52-0000-4000-8000-000000000003"
    with fake_api() as api:
        api.routes.update(_api_routes(run_id))
        config = TracerConfig(api_url=api.url, project_id=PROJECT_ID)
        tracer = AgentTracer(config)
        counter = Counter()
        agent = _order_agent(tracer, counter, skip_status=True)

        async def main():
            recording = await Recording.from_api(run_id, config)
            return await tracer.replay(recording, agent, agent_version="v2")

        result = asyncio.run(main())

        assert counter.calls == 0
        assert result.trace is not None and result.trace.uploaded is True
        [upload] = api.bodies
        assert upload["id"] == result.trace.id
        assert upload["replay_of_run_id"] == run_id
        assert upload["agent_version"] == "v2"
        kinds = [e["event_type"] for e in upload["events"]]
        assert kinds == ["agent_start", "tool_call", "tool_response", "agent_end"]
