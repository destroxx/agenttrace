"""Tests for @tracer.tool and for concurrent recording."""

from __future__ import annotations

import asyncio

import pytest
from fake_api import fake_api

from agenttrace import AgentTracer, TracerConfig

PROJECT_ID = "3f1d9c88-5b7a-4f2e-9f6c-1b2a3c4d5e6f"


def _events(trace, event_type: str) -> list:
    return [event for event in trace.events if event.event_type == event_type]


def test_decorator_records_a_sync_function() -> None:
    tracer = AgentTracer(TracerConfig())

    @tracer.tool
    def add(left: int, right: int = 2) -> int:
        return left + right

    with tracer.trace("agent") as trace:
        assert add(3) == 5

    call = _events(trace, "tool_call")[0]
    response = _events(trace, "tool_response")[0]
    assert call.tool_name == "add"
    # apply_defaults() means an omitted argument is still recorded.
    assert call.arguments == {"left": 3, "right": 2}
    assert response.response == 5
    assert response.call_id == call.call_id
    assert response.duration_ms is not None and response.duration_ms >= 0


def test_decorator_records_an_async_function() -> None:
    tracer = AgentTracer(TracerConfig())

    @tracer.tool
    async def fetch(order_id: str) -> dict:
        await asyncio.sleep(0)
        return {"order_id": order_id}

    async def main():
        async with tracer.trace("agent") as trace:
            assert await fetch("A-1") == {"order_id": "A-1"}
        return trace

    trace = asyncio.run(main())

    call = _events(trace, "tool_call")[0]
    assert call.tool_name == "fetch"
    assert call.arguments == {"order_id": "A-1"}
    assert _events(trace, "tool_response")[0].response == {"order_id": "A-1"}


def test_decorator_accepts_a_custom_name() -> None:
    tracer = AgentTracer(TracerConfig())

    @tracer.tool(name="lookup_order")
    def fetch(order_id: str) -> str:
        return "ok"

    with tracer.trace("agent") as trace:
        fetch("A-1")

    assert _events(trace, "tool_call")[0].tool_name == "lookup_order"
    # functools.wraps keeps the function's own identity intact.
    assert fetch.__name__ == "fetch"


def test_decorator_drops_self_on_methods() -> None:
    tracer = AgentTracer(TracerConfig())

    class Client:
        @tracer.tool
        def fetch(self, order_id: str) -> str:
            return f"order {order_id}"

    with tracer.trace("agent") as trace:
        assert Client().fetch("A-1") == "order A-1"

    assert _events(trace, "tool_call")[0].arguments == {"order_id": "A-1"}


def test_decorator_reraises_the_original_exception() -> None:
    tracer = AgentTracer(TracerConfig())
    boom = RuntimeError("tool exploded")

    @tracer.tool
    def failing(order_id: str) -> None:
        raise boom

    with tracer.trace("agent") as trace, pytest.raises(RuntimeError) as excinfo:
        failing("A-1")

    assert excinfo.value is boom
    call = _events(trace, "tool_call")[0]
    error = _events(trace, "error")[0]
    assert error.call_id == call.call_id
    assert error.response == {"type": "RuntimeError", "message": "tool exploded"}
    assert error.duration_ms is not None
    # The trace itself succeeded: the agent handled the tool failure.
    assert trace.status == "completed"


def test_decorator_without_an_active_trace_just_calls() -> None:
    tracer = AgentTracer(TracerConfig())

    @tracer.tool
    def add(left: int, right: int) -> int:
        return left + right

    assert add(1, 2) == 3
    assert tracer.completed_traces == ()


def test_parallel_tool_calls_pair_by_call_id() -> None:
    tracer = AgentTracer(TracerConfig())

    @tracer.tool
    async def get_order(order_id: str) -> dict:
        # Stagger the two so they genuinely interleave.
        await asyncio.sleep(0.02 if order_id == "A-1" else 0.01)
        return {"order_id": order_id}

    async def main():
        async with tracer.trace("agent") as trace:
            await asyncio.gather(get_order("A-1"), get_order("B-2"))
        return trace

    trace = asyncio.run(main())

    calls = {event.call_id: event.arguments["order_id"] for event in _events(trace, "tool_call")}
    responses = {
        event.call_id: event.response["order_id"] for event in _events(trace, "tool_response")
    }
    assert len(calls) == 2
    assert calls == responses


def test_concurrent_traces_do_not_mix() -> None:
    tracer = AgentTracer(TracerConfig())

    @tracer.tool
    async def echo(value: int) -> int:
        await asyncio.sleep(0.01)
        return value

    async def one(value: int):
        async with tracer.trace(f"agent-{value}") as trace:
            await echo(value)
        return trace

    async def main():
        return await asyncio.gather(*(one(value) for value in range(5)))

    traces = asyncio.run(main())

    assert len(traces) == 5
    for value, trace in enumerate(traces):
        assert trace.name == f"agent-{value}"
        calls = _events(trace, "tool_call")
        assert len(calls) == 1
        assert calls[0].arguments == {"value": value}
        assert _events(trace, "tool_response")[0].response == value


def test_sequences_are_unique_and_increasing() -> None:
    tracer = AgentTracer(TracerConfig())

    @tracer.tool
    async def work(index: int) -> int:
        await asyncio.sleep(0)
        return index

    async def main():
        async with tracer.trace("agent") as trace:
            await asyncio.gather(*(work(index) for index in range(20)))
        return trace

    trace = asyncio.run(main())

    sequences = [event.sequence for event in trace.events]
    assert len(sequences) == len(set(sequences))
    assert sequences == sorted(sequences)
    assert sequences[0] == 0


def test_sync_tools_in_threads_keep_sequences_unique() -> None:
    """A sync tool may run in a worker thread; the counter is locked for that."""
    tracer = AgentTracer(TracerConfig())

    @tracer.tool
    def work(index: int) -> int:
        return index

    async def main():
        async with tracer.trace("agent") as trace:
            await asyncio.gather(*(asyncio.to_thread(work, index) for index in range(30)))
        return trace

    trace = asyncio.run(main())

    sequences = [event.sequence for event in trace.events]
    assert len(sequences) == len(set(sequences))
    assert len(_events(trace, "tool_call")) == 30
    assert len(_events(trace, "tool_response")) == 30


def test_decorated_tools_reach_the_upload() -> None:
    with fake_api() as api:
        tracer = AgentTracer(TracerConfig(api_url=api.url, project_id=PROJECT_ID))

        @tracer.tool
        async def get_order(order_id: str) -> dict:
            return {"order_id": order_id}

        async def main():
            async with tracer.trace("support-agent", input={"q": "?"}) as trace:
                await asyncio.gather(get_order("A-1"), get_order("B-2"))
                trace.set_output({"done": True})
            return trace

        trace = asyncio.run(main())

        assert trace.uploaded is True
        body = api.requests[0].body
        calls = {e["call_id"]: e["arguments"]["order_id"] for e in body["events"]
                 if e["event_type"] == "tool_call"}
        responses = {e["call_id"]: e["response"]["order_id"] for e in body["events"]
                     if e["event_type"] == "tool_response"}
        assert calls == responses
        assert len(calls) == 2
