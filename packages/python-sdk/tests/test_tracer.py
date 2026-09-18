"""Tests for the AgentTracer recording skeleton."""

from __future__ import annotations

import pytest

from agenttrace import AgentTracer, TracerConfig, __version__


def test_package_exposes_version() -> None:
    assert __version__ == "0.1.0"


def test_config_reads_environment(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("AGENTTRACE_API_URL", "https://api.example.com/")
    monkeypatch.setenv("AGENTTRACE_API_KEY", "secret-key")

    config = TracerConfig.from_env()

    assert config.api_url == "https://api.example.com"
    assert config.api_key == "secret-key"
    assert "secret-key" not in repr(config)


def test_config_defaults_to_localhost(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("AGENTTRACE_API_URL", raising=False)
    monkeypatch.delenv("AGENTTRACE_API_KEY", raising=False)

    config = TracerConfig.from_env()

    assert config.api_url == "http://localhost:8000"
    assert config.api_key is None


def test_trace_records_tool_calls() -> None:
    tracer = AgentTracer(TracerConfig())

    with tracer.trace("checkout-agent", user="u-1") as trace:
        tracer.record_tool_call("search", {"q": "shoes"}, response=["a", "b"])
        tracer.record_tool_call("add_to_cart", {"sku": "123"}, response={"ok": True})

    assert trace.metadata == {"user": "u-1"}
    assert [call.name for call in trace.tool_calls] == ["search", "add_to_cart"]
    assert trace.tool_calls[0].arguments == {"q": "shoes"}
    assert trace.tool_calls[1].response == {"ok": True}
    assert tracer.completed_traces == (trace,)
    assert tracer.active_trace is None


def test_trace_is_closed_when_the_agent_raises() -> None:
    tracer = AgentTracer(TracerConfig())

    with pytest.raises(ValueError):
        with tracer.trace("failing-agent") as trace:
            tracer.record_tool_call("search", {"q": "shoes"})
            raise ValueError("agent blew up")

    assert not trace.is_open
    assert trace.ended_at is not None
    assert len(trace.tool_calls) == 1
    assert tracer.completed_traces == (trace,)


def test_recording_outside_a_trace_is_an_error() -> None:
    tracer = AgentTracer(TracerConfig())

    with pytest.raises(RuntimeError, match="no active trace"):
        tracer.record_tool_call("search", {"q": "shoes"})


def test_nested_traces_are_rejected() -> None:
    tracer = AgentTracer(TracerConfig())

    with tracer.trace("outer"):
        with pytest.raises(RuntimeError, match="already active"):
            with tracer.trace("inner"):
                pass


def test_closed_trace_rejects_further_tool_calls() -> None:
    tracer = AgentTracer(TracerConfig())
    with tracer.trace("agent") as trace:
        pass

    with pytest.raises(RuntimeError, match="already closed"):
        trace.add_tool_call(_any_call())


def _any_call():
    from agenttrace import ToolCall

    return ToolCall(name="search", arguments={})
